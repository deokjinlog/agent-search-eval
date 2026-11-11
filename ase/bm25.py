"""BM25 arm: 단어 검색 1회.

질문 텍스트 하나로 기준 시점의 코드 파일(테스트 제외)을 순위 매기고 상위 k개를 제출한다.
한국어는 형태소 분석기 없이 글자 2-gram으로, 코드는 snake_case·camelCase를 쪼갠 단어로 센다.

    python -m ase.bm25 --golden data/golden.jsonl -o results/bm25.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

from .common import code_files, load_golden, precision, recall, snapshot

K1 = 1.5
B = 0.75
SUBMIT_K = 5
DIAG_KS = (1, 3, 5, 10)

ASCII_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*|[0-9]+")
HANGUL_RUN = re.compile(r"[가-힣]+")
CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for word in ASCII_WORD.findall(text):
        parts = [p.lower() for p in CAMEL.findall(word)]
        tokens.append(word.lower())
        if len(parts) > 1:
            tokens.extend(parts)
    for run in HANGUL_RUN.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return [t for t in tokens if len(t) >= 2 or "가" <= t <= "힣"]


class BM25:
    def __init__(self, docs: dict[str, list[str]], k1: float = K1, b: float = B):
        self.k1, self.b = k1, b
        self.tf = {name: Counter(toks) for name, toks in docs.items()}
        self.len = {name: len(toks) for name, toks in docs.items()}
        self.avg = sum(self.len.values()) / max(len(self.len), 1)
        df = Counter()
        for counts in self.tf.values():
            df.update(counts.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def rank(self, query: list[str]) -> list[tuple[str, float]]:
        q = Counter(query)
        scores = {}
        for name, counts in self.tf.items():
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * self.len[name] / self.avg)
            for term in q:
                f = counts.get(term)
                if f:
                    s += self.idf[term] * f * (self.k1 + 1) / (f + norm)
            scores[name] = s
        return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def run_question(q: dict) -> dict:
    root = snapshot(q)
    files = code_files(root)
    docs = {f: tokenize((root / f).read_text(encoding="utf-8", errors="ignore")) for f in files}
    ranked = [name for name, score in BM25(docs).rank(tokenize(q["question"])) if score > 0]
    gold = set(q["gold"])
    submitted = ranked[:SUBMIT_K]
    return {
        "arm": "bm25",
        "qid": q["qid"],
        "run": 0,
        "submitted": submitted,
        "submit_recall": recall(set(submitted), gold),
        "precision": precision(set(submitted), gold),
        "recall_at": {str(k): recall(set(ranked[:k]), gold) for k in DIAG_KS},
        "candidates": len(files),
        "gold_ranks": {g: (ranked.index(g) + 1 if g in ranked else None) for g in sorted(gold)},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", default="data/golden.jsonl")
    ap.add_argument("-o", "--output", type=Path, default=Path("results/bm25.jsonl"))
    args = ap.parse_args(argv)
    rows = [run_question(q) for q in load_golden(args.golden)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    mean = sum(r["submit_recall"] for r in rows) / len(rows)
    print(f"BM25 질문 {len(rows)}개, Submit-Recall@{SUBMIT_K} 평균 {mean:.3f} → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
