"""제출 개수와 Submit-Recall 그림: BM25 상위 k개 곡선 위에 에이전트 평균을 찍는다.

    python -m ase.chart --models haiku sonnet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
SERIES = {"bm25": "#2a78d6", "haiku": "#eb6834", "sonnet": "#1baf7a"}
NAMES = {"haiku": "Haiku 에이전트", "sonnet": "Sonnet 에이전트"}


def korean_font() -> str | None:
    for f in font_manager.findSystemFonts():
        if "NotoSansCJK" in f.replace(" ", "") or "NotoSansKR" in f:
            font_manager.fontManager.addfont(f)
    names = {f.name for f in font_manager.fontManager.ttflist}
    return next((n for n in ("Noto Sans CJK KR", "Noto Sans KR", "Noto Sans CJK JP") if n in names), None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["haiku", "sonnet"])
    ap.add_argument("-o", "--output", default="results/recall_vs_submitted.png")
    args = ap.parse_args(argv)
    s = json.loads(Path("results/summary.json").read_text(encoding="utf-8"))

    family = korean_font()
    if family:
        plt.rcParams["font.family"] = family
    plt.rcParams.update({"axes.edgecolor": GRID, "axes.labelcolor": TEXT_2, "xtick.color": TEXT_2,
                         "ytick.color": TEXT_2, "font.size": 11})

    fig, ax = plt.subplots(figsize=(7.2, 4.4), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    ks = [int(k) for k in s["bm25"]["recall_at"]]
    ys = [s["bm25"]["recall_at"][str(k)] for k in ks]
    ax.plot(ks, ys, color=SERIES["bm25"], linewidth=2, marker="o", markersize=6,
            markeredgecolor=SURFACE, markeredgewidth=1.5, label="BM25 (상위 k개 제출)", zorder=3)
    for k, y in zip(ks, ys):
        ax.annotate(f"k={k}", (k, y), textcoords="offset points", xytext=(6, -14), color=TEXT_2, fontsize=9)
    ax.annotate("BM25 (상위 k개 제출)", (ks[-1], ys[-1]), textcoords="offset points", xytext=(-150, 10),
                color=TEXT, fontsize=10)

    # 라벨은 짧게, 점 오른쪽 위·아래로 나눠 선과 서로를 피한다 (전체 이름은 범례에)
    placement = {"sonnet": ((10, 6), "bottom"), "haiku": ((10, -6), "top")}
    for m in args.models:
        a = s["agents"][m]
        x, y, sd = a["submitted_mean"], a["submit_recall"], a["submit_recall_run_std"]
        ax.errorbar([x], [y], yerr=[[sd], [sd]], fmt="o", color=SERIES[m], markersize=9,
                    markeredgecolor=SURFACE, markeredgewidth=2, elinewidth=2, capsize=0, label=NAMES[m], zorder=4)
        offset, va = placement.get(m, ((10, 0), "center"))
        ax.annotate(f"{m.capitalize()} {y:.2f}", (x, y), textcoords="offset points", xytext=offset,
                    ha="left", va=va, color=TEXT, fontsize=10)

    ax.set_xlim(0, 10.6)
    ax.set_ylim(0, 1)
    ax.set_xticks([1, 2, 3, 5, 10])
    ax.set_xlabel("제출한 파일 수 (에이전트는 평균)")
    ax.set_ylabel("Submit-Recall")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, loc="lower right", labelcolor=TEXT, fontsize=9)
    ax.set_title("같은 개수를 내면 에이전트가 더 찾는다", loc="left", color=TEXT, fontsize=12, pad=12)
    fig.text(0.01, 0.01, "질문 30개, 에이전트는 질문마다 3번 실행. 세로 막대는 실행 간 표준편차.", color=TEXT_2, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, facecolor=SURFACE)
    print(f"→ {args.output} (font: {family})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
