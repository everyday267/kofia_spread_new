"""메일 본문용 정적 차트 (PNG).

차트 1: 등급별 국고채 대비 신용스프레드 추이
차트 2: AAA 대비 보증차익(AA- ~ A-) 추이 + 보증료 밴드(선택)
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd

# 범주형 팔레트 — 고정 순서 (등급이 바뀌어도 색이 따라가도록 등급에 고정 매핑)
GRADE_COLOR = {
    "AAA": "#2a78d6",   # blue
    "AA-": "#1baf7a",   # aqua
    "A+":  "#eda100",   # yellow
    "A":   "#e87ba4",   # magenta
    "A-":  "#eb6834",   # orange
    "BBB+": "#6250d6",  # violet
}
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def _setup_font():
    for name in ("NanumGothic", "Noto Sans CJK KR", "Malgun Gothic", "AppleGothic"):
        if any(name in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


def _base_ax(title: str, ylabel: str):
    fig, ax = plt.subplots(figsize=(9, 4.4), dpi=130)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=12, color=INK, pad=24)
    ax.set_ylabel(ylabel, color=INK_2, fontsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%y.%m"))
    return fig, ax


def _lines(ax, df: pd.DataFrame, grades: list[str]):
    """2px 선 + 우측 끝 직접 라벨(등급·최근값). 라벨 겹침은 최소 간격으로 밀어냄."""
    ends = []
    for g in grades:
        s = df[g].dropna()
        if s.empty:
            continue
        ax.plot(s.index, s.values, color=GRADE_COLOR.get(g, INK_2), linewidth=2, label=g)
        ends.append([s.values[-1], g, s.index[-1]])
    if not ends:
        return
    lo, hi = ax.get_ylim()
    min_gap = (hi - lo) * 0.055
    ends.sort(key=lambda e: e[0])
    ys = [ends[0][0]]
    for v, _, _ in ends[1:]:
        ys.append(max(v, ys[-1] + min_gap))
    for (v, g, x), y in zip(ends, ys):
        ax.annotate(f"{g} {v:.0f}", xy=(x, y), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8, color=INK)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=8,
              ncol=len(ends), labelcolor=INK_2, borderaxespad=0.2)


def chart_credit_spread(spread: pd.DataFrame, tenor_label: str, out: Path) -> Path:
    _setup_font()
    grades = [g for g in ["AAA", "AA-", "A+", "A", "A-", "BBB+"] if g in spread]
    fig, ax = _base_ax(f"회사채 신용스프레드 (국고채 {tenor_label} 대비)", "bp")
    _lines(ax, spread, grades)
    ax.set_xlim(right=spread.index.max() + (spread.index.max() - spread.index.min()) * 0.09)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    return out


def chart_pickup(pickup: pd.DataFrame, tenor_label: str, out: Path,
                 fee_band_bp: tuple[float, float] | None = None,
                 premium_bp: float = 0.0) -> Path:
    _setup_font()
    grades = [g for g in ["AA-", "A+", "A", "A-"] if g in pickup]
    sub = f" · SGI보증물 프리미엄 {premium_bp:g}bp 차감 전" if premium_bp else ""
    fig, ax = _base_ax(f"ABS보증 차익: 무보증 등급 − AAA ({tenor_label}){sub}", "bp")
    if fee_band_bp:
        lo, hi = fee_band_bp
        ax.axhspan(lo + premium_bp, hi + premium_bp, color="#d9d7d0", alpha=0.45, linewidth=0)
        ax.text(pickup.index.min(), hi + premium_bp, f" 보증료 밴드 {lo:g}~{hi:g}bp",
                va="bottom", fontsize=8, color=INK_2)
    _lines(ax, pickup, grades)
    ax.axhline(0, color=INK_2, linewidth=0.8)
    ax.set_xlim(right=pickup.index.max() + (pickup.index.max() - pickup.index.min()) * 0.09)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    return out
