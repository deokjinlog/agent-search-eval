"""후속 실험 그림: arm마다 'BM25 상위 5개와의 Submit-Recall 차이'와 95% 구간.

    python -m ase.chart_followup
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .chart import GRID, SERIES, SURFACE, TEXT, TEXT_2, korean_font  # noqa: E402


def rows(summary: dict, followup: dict) -> list[tuple[str, str, dict, float]]:
    a, f = summary["agents"], followup["arms"]
    return [
        ("Haiku, 원래 프롬프트", "haiku", a["haiku"]["vs_bm25_top5"], a["haiku"]["submitted_mean"]),
        ("Sonnet, 원래 프롬프트", "sonnet", a["sonnet"]["vs_bm25_top5"], a["sonnet"]["submitted_mean"]),
        ("Haiku, 최대 5개 프롬프트", "haiku", f["haiku-upto5"]["vs_bm25_top5"], f["haiku-upto5"]["submitted_mean"]),
        ("Grep 후보 → BM25 (Haiku 실행)", "haiku", f["haiku-grep-bm25"]["vs_bm25_top5"], f["haiku-grep-bm25"]["submitted_mean"]),
        ("Grep 후보 → BM25 (Sonnet 실행)", "sonnet", f["sonnet-grep-bm25"]["vs_bm25_top5"], f["sonnet-grep-bm25"]["submitted_mean"]),
        ("Haiku가 고른 파일 + BM25 채움", "haiku", f["haiku-fill5"]["vs_bm25_top5"], f["haiku-fill5"]["submitted_mean"]),
        ("Sonnet이 고른 파일 + BM25 채움", "sonnet", f["sonnet-fill5"]["vs_bm25_top5"], f["sonnet-fill5"]["submitted_mean"]),
    ]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="results/followup_vs_bm25.png")
    args = ap.parse_args(argv)
    summary = json.loads(Path("results/summary.json").read_text(encoding="utf-8"))
    followup = json.loads(Path("results/followup.json").read_text(encoding="utf-8"))
    data = rows(summary, followup)

    family = korean_font()
    if family:
        plt.rcParams["font.family"] = family
    plt.rcParams.update({"axes.edgecolor": GRID, "axes.labelcolor": TEXT_2, "xtick.color": TEXT_2,
                         "ytick.color": TEXT, "font.size": 10})
    fig, ax = plt.subplots(figsize=(7.6, 4.6), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    ys = list(range(len(data)))[::-1]
    for y, (label, model, c, n) in zip(ys, data):
        lo, hi = c["ci95"]
        ax.plot([lo, hi], [y, y], color=SERIES[model], linewidth=2.2, solid_capstyle="round", zorder=3)
        ax.plot([c["mean"]], [y], "o", color=SERIES[model], markersize=8, markeredgecolor=SURFACE,
                markeredgewidth=2, zorder=4)
        ax.annotate(f"{c['mean']:+.3f} [{lo:+.3f}, {hi:+.3f}] · {n:.2f}개", (0.33, y), xycoords=("data", "data"),
                    va="center", ha="left", color=TEXT_2, fontsize=8.5)
    ax.axvline(0, color=TEXT, linewidth=1.2, zorder=2)
    for y in (4.5, 3.5, 1.5):
        ax.axhline(y, color=GRID, linewidth=0.8)
    ax.set_yticks(ys)
    ax.set_yticklabels([d[0] for d in data])
    ax.set_xlim(-0.25, 0.62)
    ax.set_xticks([-0.2, -0.1, 0, 0.1, 0.2, 0.3])
    ax.set_xlabel("BM25 상위 5개와의 Submit-Recall 차이 (질문 단위, 95% 구간)")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_title("고른 파일에 BM25로 5개까지 채우면 Sonnet은 앞서고 Haiku는 경계선", loc="left", color=TEXT, fontsize=12, pad=12)
    from matplotlib.lines import Line2D
    handles = [Line2D([0], [0], color=SERIES[m], marker="o", linewidth=2.2, markersize=7, markeredgecolor=SURFACE,
                      label=name) for m, name in (("haiku", "Haiku 실행"), ("sonnet", "Sonnet 실행"))]
    fig.legend(handles=handles, frameon=False, loc="lower right", bbox_to_anchor=(0.995, 0.0), ncol=2, fontsize=8,
               labelcolor=TEXT, borderaxespad=0.2)
    fig.text(0.01, 0.01, "질문 30개, 에이전트는 질문마다 3번 실행. 오른쪽 숫자는 차이 [95% 구간] · 평균 제출 수.",
             color=TEXT_2, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(args.output, facecolor=SURFACE)
    print(f"→ {args.output} (font: {family})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
