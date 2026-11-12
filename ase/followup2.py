"""후속 실험 2 요약: 한국어 질문을 영어 코드와 잇는 두 방법을 BM25 상위 5개와 비교한다.

- rewrite-<model>: 질문 재작성 + BM25 (ase.rewrite, 실행 여러 번 → 질문마다 평균)
- vector, hybrid: 다국어 임베딩, BM25와 RRF 결합 (ase.vector, 결과 파일이 있을 때만)

비교는 질문 단위 짝 비교, 부트스트랩 95% 구간(ase.report와 같은 시드). 질문 속성(has_identifier)은
4주차 실험 전에 붙인 것을 그대로 쓴다.

    python -m ase.followup2
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .common import load_golden
from .report import compare, mean, read_jsonl

ARMS = {
    "rewrite-haiku": "results/rewrite_haiku.jsonl",
    "vector": "results/vector.jsonl",
    "hybrid": "results/hybrid.jsonl",
}


def per_question(rows: list[dict], key: str = "submit_recall") -> dict[str, float]:
    by_q = defaultdict(list)
    for r in rows:
        by_q[r["qid"]].append(r[key])
    return {qid: mean(v) for qid, v in by_q.items()}


def arm_summary(golden: list[dict], base: dict[str, float], rows: list[dict]) -> dict:
    sr = per_question(rows)
    pr = per_question(rows, "precision")
    sub = per_question([{**r, "n": len(r["submitted"])} for r in rows], "n")
    out = {
        "submit_recall": mean(sr[q["qid"]] for q in golden),
        "precision": mean(pr[q["qid"]] for q in golden),
        "avg_submitted": mean(sub[q["qid"]] for q in golden),
        "vs_bm25_top5": compare([sr[q["qid"]] - base[q["qid"]] for q in golden]),
        "slices": {},
    }
    if any(r["run"] for r in rows):  # 실행이 여러 번이면 실행별 평균의 흔들림
        by_run = defaultdict(list)
        for r in rows:
            by_run[r["run"]].append(r["submit_recall"])
        run_means = [mean(v) for _, v in sorted(by_run.items())]
        out["run_means"] = run_means
    for name, cond in (("has_identifier", True), ("no_identifier", False)):
        qs = [q for q in golden if q["has_identifier"] is cond]
        out["slices"][name] = {
            "n": len(qs),
            "bm25_top5": mean(base[q["qid"]] for q in qs),
            "arm": mean(sr[q["qid"]] for q in qs),
            "vs_bm25_top5": compare([sr[q["qid"]] - base[q["qid"]] for q in qs]),
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", default="data/golden.jsonl")
    ap.add_argument("-o", "--output", type=Path, default=Path("results/followup2.json"))
    args = ap.parse_args(argv)
    golden = load_golden(args.golden)
    base = {r["qid"]: r["submit_recall"] for r in read_jsonl("results/bm25.jsonl")}
    summary = {"bm25_top5": mean(base[q["qid"]] for q in golden), "arms": {}}
    for arm, path in ARMS.items():
        if Path(path).exists():
            summary["arms"][arm] = arm_summary(golden, base, read_jsonl(path))
    cost = Path("results/rewrite_haiku_cost.json")
    if cost.exists():
        summary["rewrite_haiku_cost"] = json.loads(cost.read_text(encoding="utf-8"))
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for arm, s in summary["arms"].items():
        c = s["vs_bm25_top5"]
        ni = s["slices"]["no_identifier"]
        print(f"{arm}: Submit-Recall {s['submit_recall']:.3f} (BM25 {summary['bm25_top5']:.3f}), 차이 {c['mean']:+.3f} "
              f"[{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}] / 한국어만 {ni['n']}개 {ni['arm']:.3f} vs {ni['bm25_top5']:.3f}, "
              f"차이 {ni['vs_bm25_top5']['mean']:+.3f} [{ni['vs_bm25_top5']['ci95'][0]:+.3f}, {ni['vs_bm25_top5']['ci95'][1]:+.3f}]")
    print(f"→ {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
