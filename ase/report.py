"""BM25와 에이전트(모델별) 결과를 질문 단위로 묶어 요약한다.

- 질문마다 에이전트는 실행 3번의 평균을 쓴다.
- 실행 간 흔들림: 실행 번호(r1, r2, r3)별 전체 평균을 구해 그 표준편차를 본다.
- 비교는 두 가지로 한다.
    top5:    BM25가 늘 5개를 제출할 때
    matched: BM25도 에이전트가 그 실행에서 낸 개수만큼만 제출할 때 (최소 1개)
- 차이는 질문 단위 짝 비교, 부트스트랩 95% 구간 (시드 고정).

    python -m ase.report --models haiku sonnet
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

from .common import load_golden

SEED = 20261111
BOOT = 10000
KS = (1, 2, 3, 5, 10)


def read_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def mean(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def bootstrap(diffs: list[float], seed: int = SEED, n: int = BOOT) -> list[float]:
    rng = random.Random(seed)
    samples = sorted(mean(rng.choice(diffs) for _ in diffs) for _ in range(n))
    return [samples[int(0.025 * n)], samples[int(0.975 * n) - 1]]


def compare(diffs: list[float]) -> dict:
    return {
        "mean": mean(diffs),
        "ci95": bootstrap(diffs),
        "wins": sum(d > 1e-9 for d in diffs),
        "ties": sum(abs(d) <= 1e-9 for d in diffs),
        "losses": sum(d < -1e-9 for d in diffs),
    }


def bm25_recall_at(row: dict, k: int) -> float:
    ranks = row["gold_ranks"].values()
    return sum(1 for r in ranks if r is not None and r <= k) / len(row["gold_ranks"])


def agent_stats(golden: dict, bm25: dict, rows: list[dict]) -> dict:
    runs = defaultdict(list)
    for r in rows:
        runs[r["qid"]].append(r)
    run_ids = sorted({r["run"] for r in rows})
    run_means = [mean(r["submit_recall"] for r in rows if r["run"] == k) for k in run_ids]

    per_q = {}
    for qid in golden:
        a = runs[qid]
        per_q[qid] = {
            "sr": mean(r["submit_recall"] for r in a),
            "sr_runs": [r["submit_recall"] for r in sorted(a, key=lambda r: r["run"])],
            "precision": mean(r["precision"] for r in a),
            "read_recall": mean(r["read_recall"] for r in a),
            "grep_recall": mean(r["grep_recall"] for r in a),
            "submitted": mean(len(r["submitted"]) for r in a),
            "tokens_sum": mean(r["input_tokens_sum"] for r in a),
            "tokens_max": mean(r["input_tokens_max"] for r in a),
            "bm25_matched": mean(bm25_recall_at(bm25[qid], max(len(r["submitted"]), 1)) for r in a),
        }

    gold_read = sum(len(set(r["read"]) & set(golden[r["qid"]]["gold"])) for r in rows)
    read_not_submitted = sum(len(set(r["read"]) & set(golden[r["qid"]]["gold"]) - set(r["submitted"])) for r in rows)

    def sl(pred):
        sel = [q for q in golden.values() if pred(q)]
        return {"n": len(sel),
                "bm25_top5": mean(bm25[q["qid"]]["submit_recall"] for q in sel),
                "bm25_matched": mean(per_q[q["qid"]]["bm25_matched"] for q in sel),
                "agent": mean(per_q[q["qid"]]["sr"] for q in sel)}

    return {
        "runs": len(rows),
        "submit_recall": mean(p["sr"] for p in per_q.values()),
        "submit_recall_by_run": run_means,
        "submit_recall_run_std": st.stdev(run_means) if len(run_means) > 1 else 0.0,
        "precision": mean(p["precision"] for p in per_q.values()),
        "read_recall": mean(p["read_recall"] for p in per_q.values()),
        "grep_recall": mean(p["grep_recall"] for p in per_q.values()),
        "grep_files_listed_median": st.median(r["grep_files_listed"] for r in rows),
        "submitted_mean": mean(p["submitted"] for p in per_q.values()),
        "submitted_dist": dict(sorted(Counter(len(r["submitted"]) for r in rows).items())),
        "empty_submissions": sum(1 for r in rows if not r["submitted"]),
        "input_tokens_sum_median": st.median(r["input_tokens_sum"] for r in rows),
        "input_tokens_max_median": st.median(r["input_tokens_max"] for r in rows),
        "llm_calls_mean": mean(r["llm_calls"] for r in rows),
        "tool_calls_mean": mean(r["tool_calls"] for r in rows),
        "tool_counts": {t: sum(r["tool_counts"][t] for r in rows) for t in ("Grep", "Glob", "Read")},
        "duration_s_median": round(st.median(r["duration_s"] for r in rows), 1),
        "cost_usd_sum": sum(r["cost_usd"] or 0 for r in rows),
        "gold_read": gold_read,
        "gold_read_not_submitted": read_not_submitted,
        "origins": dict(Counter(o for r in rows for o in r["origins"].values())),
        "vs_bm25_top5": compare([per_q[q]["sr"] - bm25[q]["submit_recall"] for q in golden]),
        "vs_bm25_matched": compare([per_q[q]["sr"] - per_q[q]["bm25_matched"] for q in golden]),
        "bm25_matched_recall": mean(p["bm25_matched"] for p in per_q.values()),
        "slices": {
            "has_identifier": sl(lambda q: q["has_identifier"]),
            "no_identifier": sl(lambda q: not q["has_identifier"]),
            "gold_1": sl(lambda q: len(q["gold"]) == 1),
            "gold_2plus": sl(lambda q: len(q["gold"]) >= 2),
        },
        "per_question": per_q,
    }


def summarize(models: list[str], golden_path="data/golden.jsonl", bm25_path="results/bm25.jsonl") -> dict:
    golden = {q["qid"]: q for q in load_golden(golden_path)}
    bm25 = {r["qid"]: r for r in read_jsonl(bm25_path)}
    return {
        "questions": len(golden),
        "bm25": {
            "submit_recall_top5": mean(bm25[q]["submit_recall"] for q in golden),
            "precision_top5": mean(bm25[q]["precision"] for q in golden),
            "recall_at": {str(k): mean(bm25_recall_at(bm25[q], k) for q in golden) for k in KS},
        },
        "agents": {m: agent_stats(golden, bm25, read_jsonl(f"results/agent_{m}.jsonl")) for m in models},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", nargs="+", default=["haiku"])
    args = ap.parse_args(argv)
    s = summarize(args.models)
    out = Path("results/summary.json")
    out.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    b = s["bm25"]
    print(f"질문 {s['questions']}개")
    print(f"BM25 top5   Submit-Recall {b['submit_recall_top5']:.3f}  Precision {b['precision_top5']:.3f}  "
          f"recall@k " + ", ".join(f"{k}:{v:.3f}" for k, v in b["recall_at"].items()))
    for m, a in s["agents"].items():
        t, mt = a["vs_bm25_top5"], a["vs_bm25_matched"]
        print(f"[{m}] 실행 {a['runs']}번  Submit-Recall {a['submit_recall']:.3f} "
              f"(실행별 {', '.join(f'{x:.3f}' for x in a['submit_recall_by_run'])}, 표준편차 {a['submit_recall_run_std']:.3f})  "
              f"Precision {a['precision']:.3f}  Read-Recall {a['read_recall']:.3f}  Grep-Recall {a['grep_recall']:.3f}  제출 {a['submitted_mean']:.2f}개  Grep이 보여 준 파일 수 중앙값 {a['grep_files_listed_median']}")
        print(f"    vs BM25 top5    {t['mean']:+.3f} [{t['ci95'][0]:+.3f}, {t['ci95'][1]:+.3f}]  이김 {t['wins']} 비김 {t['ties']} 짐 {t['losses']}")
        print(f"    vs BM25 같은 개수 {mt['mean']:+.3f} [{mt['ci95'][0]:+.3f}, {mt['ci95'][1]:+.3f}]  이김 {mt['wins']} 비김 {mt['ties']} 짐 {mt['losses']}"
              f"  (BM25 같은 개수 recall {a['bm25_matched_recall']:.3f})")
        print(f"    토큰 합계 중앙값 {a['input_tokens_sum_median']:,.0f}  최대값 중앙값 {a['input_tokens_max_median']:,.0f}  "
              f"호출 {a['llm_calls_mean']:.1f}  도구 {a['tool_calls_mean']:.1f} {a['tool_counts']}  시간 중앙값 {a['duration_s_median']}s  비용 합 ${a['cost_usd_sum']:.2f}")
        print(f"    읽은 정답 {a['gold_read']}건 중 제출 안 함 {a['gold_read_not_submitted']}건, 빈 제출 {a['empty_submissions']}번, 검색어 출처 {a['origins']}")
        for k, v in a["slices"].items():
            print(f"      {k:15s} n={v['n']:2d}  BM25 top5 {v['bm25_top5']:.3f}  BM25 같은 개수 {v['bm25_matched']:.3f}  에이전트 {v['agent']:.3f}")
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
