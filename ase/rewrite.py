"""질문 재작성 arm: 한국어 질문을 영어 식별자 후보로 넓힌 뒤 BM25로 찾는다 (후속 실험 2).

한국어로만 쓴 질문은 영어로 된 코드와 겹치는 단어가 없어 BM25가 약했다(23문항 0.536).
그래서 LLM이 질문만 보고 코드에 나올 법한 영어 식별자·키워드를 추측하게 하고,
BM25 질문 = 원래 질문 + 추측한 단어로 저장소 전체 코드 파일을 순위 매겨 상위 5개를 낸다.

LLM 호출은 에이전트 arm과 같은 격리 플래그를 쓰되 도구를 모두 끄고(--tools ""),
빈 임시 폴더에서 돌려 코드도 정답도 볼 수 없게 한다. 남기는 것은 추측한 단어뿐이다.

    python -m ase.rewrite --model haiku --runs 3 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .agent import STRIP_ENV
from .bm25 import BM25, DIAG_KS, SUBMIT_K, tokenize
from .common import code_files, load_golden, precision, recall, snapshot

TIMEOUT_S = 180

PROMPT = """다음은 코드 저장소에 대한 변경 요청입니다. 이 요청을 구현할 때 코드에 나올 법한 영어 식별자(함수·변수·클래스·파일 이름 조각)와 영어 키워드를 10~20개 추측해, 공백으로 구분한 한 줄로만 쓰세요. 설명은 쓰지 마세요.

변경 요청: {question}
"""


def command(model: str, question: str) -> list[str]:
    return [
        "claude", "-p", PROMPT.format(question=question),
        "--model", model,
        "--tools", "",
        "--max-turns", "1",
        "--output-format", "json",
        "--strict-mcp-config",
        "--setting-sources", "project",
        "--no-session-persistence",
    ]


def parse_terms(text: str) -> str:
    """응답의 마지막 비어 있지 않은 줄을 추측 단어로 쓴다 (코드 펜스·백틱 제거)."""
    lines = [ln.strip().strip("`").strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("```")]
    return lines[-1] if lines else ""


def ask(model: str, question: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    with tempfile.TemporaryDirectory(prefix="ase-rewrite-") as cwd:
        try:
            proc = subprocess.run(command(model, question), cwd=cwd, env=env,
                                  capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return {"ok": False, "terms": "", "cost_usd": 0.0, "error": "timeout"}
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "terms": "", "cost_usd": 0.0, "error": proc.stderr[-200:]}
    ok = not out.get("is_error") and out.get("subtype") == "success"
    return {"ok": ok, "terms": parse_terms(out.get("result", "")) if ok else "",
            "cost_usd": float(out.get("total_cost_usd") or 0.0)}


def score(q: dict, terms: str, docs_cache: dict) -> dict:
    root = snapshot(q)
    if q["qid"] not in docs_cache:
        files = code_files(root)
        docs_cache[q["qid"]] = BM25({f: tokenize((root / f).read_text(encoding="utf-8", errors="ignore")) for f in files})
    ranked = [name for name, s in docs_cache[q["qid"]].rank(tokenize(q["question"]) + tokenize(terms)) if s > 0]
    gold = set(q["gold"])
    submitted = ranked[:SUBMIT_K]
    return {
        "submitted": submitted,
        "submit_recall": recall(set(submitted), gold),
        "precision": precision(set(submitted), gold),
        "recall_at": {str(k): recall(set(ranked[:k]), gold) for k in DIAG_KS},
        "gold_ranks": {g: (ranked.index(g) + 1 if g in ranked else None) for g in sorted(gold)},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", default="data/golden.jsonl")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args(argv)
    out_path = args.output or Path(f"results/rewrite_{args.model}.jsonl")
    qs = load_golden(args.golden)
    jobs = [(q, n) for n in range(1, args.runs + 1) for q in qs]
    answers: dict[tuple[str, int], dict] = {}
    with ThreadPoolExecutor(args.jobs) as pool:
        futures = {pool.submit(ask, args.model, q["question"]): (q["qid"], n) for q, n in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            key = futures[fut]
            answers[key] = fut.result()
            print(f"[{i}/{len(jobs)}] {key[0]} r{key[1]} {'ok' if answers[key]['ok'] else 'FAIL'}", flush=True)
    docs_cache: dict = {}
    rows = []
    for q, n in jobs:
        a = answers[(q["qid"], n)]
        rows.append({"arm": f"rewrite-{args.model}", "qid": q["qid"], "run": n, "ok": a["ok"], "terms": a["terms"],
                     **score(q, a["terms"], docs_cache)})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    cost = sum(a["cost_usd"] for a in answers.values())
    # 사용량은 실행별로 남기지 않고 합계만 따로 둔다 (CLAUDE.md: 사용량 이벤트는 커밋하지 않음)
    Path(f"results/rewrite_{args.model}_cost.json").write_text(
        json.dumps({"calls": len(answers), "failed": sum(not a["ok"] for a in answers.values()),
                    "cost_usd_sum": round(cost, 4)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mean = sum(r["submit_recall"] for r in rows) / len(rows)
    print(f"재작성 + BM25 ({args.model}) 실행 {len(rows)}개, Submit-Recall@{SUBMIT_K} 평균 {mean:.3f}, 추정 비용 ${cost:.4f} → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
