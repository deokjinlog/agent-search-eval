"""Vector RAG arm: 다국어 임베딩으로 파일 순위를 매긴다 (후속 실험 2, 실행 대기).

한국어 질문과 영어 코드 사이를 단어가 아니라 뜻으로 잇는지 본다.

- 모델: BAAI/bge-m3 (dense 벡터만 사용, 질문 앞에 지시문을 붙이지 않음)
- 조각: 파일을 60줄 창, 40줄 간격(20줄 겹침)으로 자르고, 조각마다 첫 줄에 파일 경로를 붙인다
- 파일 점수: 그 파일 조각들과 질문의 코사인 유사도 가운데 최댓값
- 제출: 상위 5개 (BM25 arm과 같은 후보 파일, 테스트 제외)
- 보조 arm (hybrid): BM25 순위와 벡터 순위를 RRF(k=60)로 합쳐 상위 5개

이 환경에는 임베딩 모델이 없어서 아직 돌리지 않았다. 네트워크가 되는 곳에서
`pip install sentence-transformers` 뒤에 실행한다 (모델은 처음 실행 때 내려받음, 약 2.3GB).

    python -m ase.vector --model BAAI/bge-m3
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Callable

from .bm25 import DIAG_KS, SUBMIT_K
from .common import code_files, load_golden, precision, recall, snapshot
from .followup import bm25_order

MODEL = "BAAI/bge-m3"
CHUNK_LINES = 60
STRIDE = 40
RRF_K = 60

Embed = Callable[[list[str]], list[list[float]]]


def chunks(path: str, text: str, size: int = CHUNK_LINES, stride: int = STRIDE) -> list[str]:
    """size줄 창을 stride줄 간격으로 자른다. 마지막 창은 파일 끝에 맞춰 꼬리를 빠뜨리지 않는다."""
    lines = text.splitlines()
    if not lines:
        return [path]
    starts = list(range(0, max(len(lines) - size, 0) + 1, stride))
    if starts[-1] + size < len(lines):
        starts.append(len(lines) - size)
    return [path + "\n" + "\n".join(lines[s:s + size]) for s in starts]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def rank_files(question: str, texts: dict[str, str], embed: Embed) -> list[tuple[str, float]]:
    """파일 점수 = 조각과 질문의 코사인 유사도 최댓값 (embed는 정규화된 벡터를 돌려준다고 가정)."""
    items = [(f, c) for f in sorted(texts) for c in chunks(f, texts[f])]
    vecs = embed([c for _, c in items])
    q = embed([question])[0]
    best: dict[str, float] = {}
    for (f, _), v in zip(items, vecs):
        best[f] = max(best.get(f, -math.inf), _dot(q, v))
    return sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))


def rrf(orders: list[list[str]], k: int = RRF_K) -> list[str]:
    score: dict[str, float] = defaultdict(float)
    for order in orders:
        for i, f in enumerate(order):
            score[f] += 1.0 / (k + i + 1)
    return sorted(score, key=lambda f: (-score[f], f))


def row(arm: str, q: dict, ranked: list[str]) -> dict:
    gold = set(q["gold"])
    submitted = ranked[:SUBMIT_K]
    return {
        "arm": arm, "qid": q["qid"], "run": 0, "submitted": submitted,
        "submit_recall": recall(set(submitted), gold),
        "precision": precision(set(submitted), gold),
        "recall_at": {str(k): recall(set(ranked[:k]), gold) for k in DIAG_KS},
        "gold_ranks": {g: (ranked.index(g) + 1 if g in ranked else None) for g in sorted(gold)},
    }


def st_embedder(model_name: str, batch_size: int = 16) -> Embed:
    from sentence_transformers import SentenceTransformer  # 실행할 때만 필요

    model = SentenceTransformer(model_name)

    def embed(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, batch_size=batch_size, normalize_embeddings=True).tolist()

    return embed


def run(golden: list[dict], embed: Embed) -> tuple[list[dict], list[dict]]:
    vec_rows, hyb_rows = [], []
    for q in golden:
        root = snapshot(q)
        texts = {f: (root / f).read_text(encoding="utf-8", errors="ignore") for f in code_files(root)}
        vec_order = [f for f, _ in rank_files(q["question"], texts, embed)]
        vec_rows.append(row("vector", q, vec_order))
        hyb_rows.append(row("hybrid", q, rrf([bm25_order(root, q["question"]), vec_order])))
    return vec_rows, hyb_rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--golden", default="data/golden.jsonl")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--vector-output", type=Path, default=Path("results/vector.jsonl"))
    ap.add_argument("--hybrid-output", type=Path, default=Path("results/hybrid.jsonl"))
    args = ap.parse_args(argv)
    vec_rows, hyb_rows = run(load_golden(args.golden), st_embedder(args.model))
    for path, rows in ((args.vector_output, vec_rows), (args.hybrid_output, hyb_rows)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"{rows[0]['arm']}: Submit-Recall@{SUBMIT_K} 평균 {sum(r['submit_recall'] for r in rows) / len(rows):.3f} → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
