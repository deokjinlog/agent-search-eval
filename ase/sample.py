"""후보 질문에서 실험용 질문을 리포 비율대로 뽑는다 (시드 고정).

    python -m ase.sample -i data/golden_candidates.jsonl -o data/golden.jsonl --n 30 --seed 20261111
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


def stratified(rows: list[dict], n: int, seed: int) -> list[dict]:
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_repo[r["repo"]].append(r)
    rng = random.Random(seed)
    quotas = {repo: round(n * len(items) / len(rows)) for repo, items in by_repo.items()}
    picked = []
    for repo in sorted(by_repo):
        items = sorted(by_repo[repo], key=lambda r: r["qid"])
        picked += rng.sample(items, min(quotas[repo], len(items)))
    return sorted(picked, key=lambda r: (r["repo"], r["qid"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--input", type=Path, default=Path("data/golden_candidates.jsonl"))
    ap.add_argument("-o", "--output", type=Path, default=Path("data/golden.jsonl"))
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=20261111)
    args = ap.parse_args(argv)
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    picked = stratified(rows, args.n, args.seed)
    args.output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in picked), encoding="utf-8")
    print(f"후보 {len(rows)}개 중 {len(picked)}개 → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
