"""5주차 후속 실험: 고르는 단계를 바꾸면 BM25 상위 5개를 이길까.

4주차 결과에서 Haiku는 Grep 결과에 뜬 정답을 내지 않아 놓친 몫이 컸다(gold_split). 그래서 고르는 단계만 바꾼 arm 세 개를 본다.

1) haiku-upto5   프롬프트에 "가능성이 높은 순서대로 최대 5개" 한 줄만 더해 새로 돌린 Haiku (ase.agent --variant upto5)
2) grep→BM25     원래 실행에서 Grep 결과에 뜬 코드 파일만 후보로 두고, 질문 BM25 점수 순으로 5개 (새 호출 없음)
3) 에이전트+채움  에이전트가 낸 파일(최대 5개)을 앞에 두고, 모자란 만큼 2)의 순서, 그다음 저장소 전체 BM25 순서로 5개를 채움 (새 호출 없음)

비교 기준은 BM25 상위 5개(저장소 전체 대상)이고, 질문 단위 짝 비교에 부트스트랩 95% 구간을 쓴다.

    python -m ase.followup --models haiku sonnet --variant-model haiku-upto5
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .bm25 import BM25, tokenize
from .common import SNAPSHOTS, code_files, load_golden, precision, recall
from .report import compare, mean, read_jsonl
from .score import PATH_LINE, RUNS_DIR, load_events, parse_submission, rel, tool_result_text

K = 5


def bm25_order(root: Path, question: str) -> list[str]:
    """저장소의 모든 코드 파일을 질문 BM25 점수 순으로 (점수 0인 파일은 이름 순으로 뒤에)."""
    files = code_files(root)
    docs = {f: tokenize((root / f).read_text(encoding="utf-8", errors="ignore")) for f in files}
    return [name for name, _ in BM25(docs).rank(tokenize(question))]


def grep_candidates(events: list[dict], root: Path, allowed: set[str]) -> set[str]:
    """Grep 결과에 경로로 나온 코드 파일 (files_with_matches 목록과 path:line 형식)."""
    by_id, grep_ids = {}, set()
    for e in events:
        if e.get("type") == "assistant":
            for c in e["message"].get("content", []):
                if c.get("type") == "tool_use" and c["name"] == "Grep":
                    grep_ids.add(c["id"])
        elif e.get("type") == "user":
            content = e.get("message", {}).get("content", [])
            for c in content if isinstance(content, list) else []:
                if c.get("type") == "tool_result" and c.get("tool_use_id") in grep_ids:
                    by_id[c["tool_use_id"]] = tool_result_text(c.get("content"))
    found = set()
    for text in by_id.values():
        for line in text.splitlines():
            line = line.strip()
            if PATH_LINE.match(line):
                found.add(rel(line.split(":", 1)[0], root))
    return found & allowed


def rerank(candidates: set[str], order: list[str], k: int = K) -> list[str]:
    return [f for f in order if f in candidates][:k]


def fill(submitted: list[str], ranked: list[str], k: int = K) -> list[str]:
    out = list(dict.fromkeys(submitted))[:k]
    for f in ranked:
        if len(out) >= k:
            break
        if f not in out:
            out.append(f)
    return out


def offline_arms(golden: list[dict], model: str) -> dict[str, list[dict]]:
    rows = defaultdict(list)
    for q in golden:
        root = SNAPSHOTS / q["qid"]
        allowed = set(code_files(root))
        order = bm25_order(root, q["question"])
        gold = set(q["gold"])
        for path in sorted((RUNS_DIR / model / q["qid"]).glob("r*.jsonl*")):
            events = load_events(path)
            result = next((e for e in reversed(events) if e.get("type") == "result"), {})
            submitted = [rel(p, root) for p in parse_submission(result.get("result", ""))]
            cands = grep_candidates(events, root, allowed)
            ranked = rerank(cands, order, len(order))
            ranked_all = ranked + [f for f in order if f not in cands]
            for arm, sub in ((f"{model}-grep-bm25", ranked[:K]), (f"{model}-fill5", fill(submitted, ranked_all))):
                rows[arm].append({"qid": q["qid"], "submitted": sub, "candidates": len(cands),
                                  "submit_recall": recall(set(sub), gold), "precision": precision(set(sub), gold)})
    return rows


def arm_summary(golden: list[dict], bm25: dict, rows: list[dict]) -> dict:
    per_q = defaultdict(list)
    for r in rows:
        per_q[r["qid"]].append(r)
    sr = {q["qid"]: mean(r["submit_recall"] for r in per_q[q["qid"]]) for q in golden}
    out = {
        "runs": len(rows),
        "submit_recall": mean(sr.values()),
        "precision": mean(mean(r["precision"] for r in per_q[q["qid"]]) for q in golden),
        "submitted_mean": mean(len(r["submitted"]) for r in rows),
        "vs_bm25_top5": compare([sr[q["qid"]] - bm25[q["qid"]]["submit_recall"] for q in golden]),
        "gold_2plus": mean(sr[q["qid"]] for q in golden if len(q["gold"]) >= 2),
    }
    if rows and "candidates" in rows[0]:
        out["candidates_mean"] = mean(r["candidates"] for r in rows)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", default="data/golden.jsonl")
    ap.add_argument("--models", nargs="+", default=["haiku", "sonnet"])
    ap.add_argument("--variant-model", default="haiku-upto5")
    ap.add_argument("--base-model", default="haiku")
    args = ap.parse_args(argv)
    golden = load_golden(args.golden)
    bm25 = {r["qid"]: r for r in read_jsonl("results/bm25.jsonl")}
    arms = {}
    for m in args.models:
        for arm, rows in offline_arms(golden, m).items():
            arms[arm] = arm_summary(golden, bm25, rows)
    variant_rows = read_jsonl(f"results/agent_{args.variant_model}.jsonl")
    base_rows = read_jsonl(f"results/agent_{args.base_model}.jsonl")
    arms[args.variant_model] = arm_summary(golden, bm25, variant_rows)
    v = {q["qid"]: mean(r["submit_recall"] for r in variant_rows if r["qid"] == q["qid"]) for q in golden}
    b = {q["qid"]: mean(r["submit_recall"] for r in base_rows if r["qid"] == q["qid"]) for q in golden}
    out = {
        "bm25_top5": {"submit_recall": mean(bm25[q["qid"]]["submit_recall"] for q in golden),
                      "gold_2plus": mean(bm25[q["qid"]]["submit_recall"] for q in golden if len(q["gold"]) >= 2)},
        "arms": arms,
        f"{args.variant_model}_vs_{args.base_model}": compare([v[q["qid"]] - b[q["qid"]] for q in golden]),
    }
    Path("results/followup.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"BM25 상위 5개 Submit-Recall {out['bm25_top5']['submit_recall']:.3f} (정답 2개 이상 {out['bm25_top5']['gold_2plus']:.3f})")
    for name, a in arms.items():
        t = a["vs_bm25_top5"]
        extra = f"  후보 평균 {a['candidates_mean']:.1f}개" if "candidates_mean" in a else ""
        print(f"{name:18s} Submit-Recall {a['submit_recall']:.3f}  Precision {a['precision']:.3f}  제출 {a['submitted_mean']:.2f}개"
              f"  정답 2개 이상 {a['gold_2plus']:.3f}  vs BM25 top5 {t['mean']:+.3f} [{t['ci95'][0]:+.3f}, {t['ci95'][1]:+.3f}]{extra}")
    c = out[f"{args.variant_model}_vs_{args.base_model}"]
    print(f"{args.variant_model} − {args.base_model}: {c['mean']:+.3f} [{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}]  이김 {c['wins']} 비김 {c['ties']} 짐 {c['losses']}")
    print("→ results/followup.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
