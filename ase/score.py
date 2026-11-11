"""에이전트 실행 기록(stream-json)을 지표로 바꾼다.

- 제출: 마지막 답에서 찾은 마지막 JSON 배열
- Read-Recall: Read 도구로 한 번이라도 연 파일 기준
- Grep-Recall: 정답 파일 경로가 Grep 결과에 한 번이라도 나온 비율 (Glob 목록은 빼고 셈)
- Submit-Recall, Precision: 제출 기준
- 토큰: 호출(assistant 메시지 id)마다 input 합계 = input_tokens + cache_creation + cache_read
- 검색어 출처: 정답 파일을 처음 읽기 직전의 Grep/Glob 패턴이
    issue  질문에 있던 단어만 씀
    obs    질문에도, 앞서 자기가 넣은 검색어에도 없고, 앞선 도구 결과에서 본 단어를 씀
    guess  질문에도 도구 결과에도 없는 단어를 씀 (모델이 떠올린 단어)
    none   검색 없이 읽었거나 패턴에 단어가 없음 (목록 보고 고름)

    python -m ase.score --model haiku   # → results/agent_haiku.jsonl
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path

from .common import ROOT, SNAPSHOTS, load_golden, precision, recall

RUNS_DIR = ROOT / "runs"
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]+|[가-힣]{2,}")
PATH_LINE = re.compile(r"^[\w./-]+\.[A-Za-z0-9]+(:|$)")


def path_listed(path: str, text: str) -> bool:
    """도구 결과 텍스트에 이 상대경로가 한 줄의 경로로 나왔는가 (files_with_matches 목록, path:line 형식)."""
    return re.search(r"(^|[\s/:\"'])" + re.escape(path) + r"($|[\s:\"',])", text, re.M) is not None
JSON_ARRAY = re.compile(r"\[[^\[\]]*\]", re.S)


def rel(path: str, root: Path) -> str:
    """스냅샷 기준 상대경로로 맞춘다 (절대경로, './' 앞머리 제거)."""
    p = path.strip()
    prefix = str(root).rstrip("/") + "/"
    if p.startswith(prefix):
        p = p[len(prefix):]
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def parse_submission(text: str) -> list[str]:
    for chunk in reversed(JSON_ARRAY.findall(text or "")):
        try:
            items = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(items, list) and all(isinstance(x, str) for x in items):
            return items
    return []


def tool_result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def load_events(path: Path) -> list[dict]:
    raw = gzip.decompress(path.read_bytes()).decode("utf-8") if path.suffix == ".gz" else path.read_text(encoding="utf-8")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def classify(pattern_words: list[str], question: str, seen_inputs: str, seen_results: str) -> str:
    if not pattern_words:
        return "none"
    q = question.lower()
    not_in_q = [w for w in pattern_words if w.lower() not in q]
    if not not_in_q:
        return "issue"
    obs = [w for w in not_in_q if w.lower() not in seen_inputs and w.lower() in seen_results]
    return "obs" if obs else "guess"


def score_run(q: dict, path: Path, model: str = "haiku") -> dict:
    root = SNAPSHOTS / q["qid"]
    events = load_events(path)
    usage_by_call: dict[str, dict] = {}
    steps: list[dict] = []  # 도구 호출 순서대로 {name, input, result}
    by_id: dict[str, dict] = {}
    result = {}
    for e in events:
        if e.get("type") == "assistant":
            m = e["message"]
            u = m.get("usage") or {}
            prev = usage_by_call.get(m["id"], {})
            usage_by_call[m["id"]] = {k: max(prev.get(k, 0) or 0, u.get(k, 0) or 0) for k in
                                      ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")}
            for c in m.get("content", []):
                if c.get("type") == "tool_use":
                    step = {"name": c["name"], "input": c.get("input", {}), "result": ""}
                    steps.append(step)
                    by_id[c["id"]] = step
        elif e.get("type") == "user":
            content = e.get("message", {}).get("content", [])
            for c in content if isinstance(content, list) else []:
                if c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                    by_id[c["tool_use_id"]]["result"] = tool_result_text(c.get("content"))
        elif e.get("type") == "result":
            result = e

    gold = set(q["gold"])
    grep_text = "\n".join(s["result"] for s in steps if s["name"] == "Grep")
    grep_hits = {g for g in gold if path_listed(g, grep_text)}
    grep_files = {line.split(":", 1)[0].strip() for line in grep_text.splitlines()
                  if PATH_LINE.match(line.strip())}
    submitted = [rel(p, root) for p in parse_submission(result.get("result", ""))]
    reads = [rel(s["input"].get("file_path", ""), root) for s in steps if s["name"] == "Read"]
    per_call = [u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"]
                for u in usage_by_call.values()]

    # 정답 파일을 처음 읽기 직전 검색어의 출처
    origins = {}
    for g in sorted(gold):
        idx = next((i for i, s in enumerate(steps) if s["name"] == "Read" and rel(s["input"].get("file_path", ""), root) == g), None)
        if idx is None:
            continue
        prev = next((i for i in range(idx - 1, -1, -1) if steps[i]["name"] in ("Grep", "Glob")), None)
        if prev is None:
            origins[g] = "none"
            continue
        words = WORD.findall(str(steps[prev]["input"].get("pattern", "")))
        seen_inputs = " ".join(json.dumps(s["input"], ensure_ascii=False) for s in steps[:prev]).lower()
        seen_results = " ".join(s["result"] for s in steps[:prev]).lower()
        origins[g] = classify(words, q["question"], seen_inputs, seen_results)

    return {
        "arm": f"agent-{model}",
        "qid": q["qid"],
        "run": int(path.name.split(".")[0].lstrip("r")),
        "submitted": submitted,
        "read": sorted(set(reads)),
        "submit_recall": recall(set(submitted), gold),
        "precision": precision(set(submitted), gold),
        "read_recall": recall(set(reads), gold),
        "grep_recall": len(grep_hits) / len(gold) if gold else 0.0,
        "grep_files_listed": len(grep_files),
        "input_tokens_sum": sum(per_call),
        "input_tokens_max": max(per_call) if per_call else 0,
        "output_tokens_sum": sum(u["output_tokens"] for u in usage_by_call.values()),
        "llm_calls": len(usage_by_call),
        "tool_calls": len(steps),
        "tool_counts": {n: sum(s["name"] == n for s in steps) for n in ("Grep", "Glob", "Read")},
        "origins": origins,
        "cost_usd": result.get("total_cost_usd"),
        "duration_s": round((result.get("duration_ms") or 0) / 1000, 1),
        "status": result.get("subtype", "missing"),
        "result_usage_input_total": sum((result.get("usage") or {}).get(k, 0) or 0 for k in
                                        ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", default="data/golden.jsonl")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args(argv)
    args.output = args.output or Path(f"results/agent_{args.model}.jsonl")
    rows = []
    for q in load_golden(args.golden):
        for path in sorted((RUNS_DIR / args.model / q["qid"]).glob("r*.jsonl*")):
            rows.append(score_run(q, path, args.model))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"에이전트 실행 {len(rows)}개 → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
