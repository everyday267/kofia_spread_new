"""회사채 신용스프레드 이력 누적 + ABS보증 메리트 지표 계산.

데이터 모델 (long format, data/spread_history.csv)
    date   : 기준일 YYYYMMDD (str)
    tenor  : KOFIA remainDayCnt 코드 (str, 예: "3")
    grade  : "국고채" 또는 정규화된 등급명 (AAA, AA+, AA, AA-, A+, A, A-, BBB+ ...)
    value  : KOFIA 원값 (%)

지표 정의
    credit_spread_bp = (등급금리 - 국고채금리) * 100
    pickup_bp        = (등급금리 - AAA금리) * 100      ← SGI 보증(AAA 부여) 시 발행사 금리 절감폭
    net_pickup_bp    = pickup_bp - SGI_PREMIUM_BP     ← SGI 보증물이 순수 AAA 대비 더 받는 프리미엄 차감
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

GOV = "국고채"
GRADE_ORDER = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
               "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-"]
FOCUS_GRADES = ["AA-", "A+", "A", "A-"]           # 취급 범위 (무보증 A-까지)
REFERENCE_GRADES = ["AAA", "BBB+"]               # 기준선 / 경색 신호
HIST_COLS = ["date", "tenor", "grade", "value"]


def normalize_grade(name: str) -> str:
    """KOFIA 등급명 표기 차이 흡수 (AA0→AA, A0→A, 공백 제거)."""
    n = (name or "").strip().replace(" ", "").upper()
    for base in ("AA", "A", "BBB", "BB"):
        if n == f"{base}0":
            return base
    return n


# ---------------------------------------------------------------- 이력 누적
def wide_to_long(df_wide: pd.DataFrame, tenor: str) -> pd.DataFrame:
    """kofia_spread.parse_body() 결과(기준일, 국고채금리, 등급...) → long."""
    if df_wide.empty:
        return pd.DataFrame(columns=HIST_COLS)
    d = df_wide.rename(columns={"기준일": "date", "국고채금리": GOV})
    long = d.melt(id_vars="date", var_name="grade", value_name="value")
    long["grade"] = long["grade"].map(lambda g: g if g == GOV else normalize_grade(g))
    long["tenor"] = str(tenor)
    long["date"] = long["date"].astype(str)
    return long.dropna(subset=["value"])[HIST_COLS]


def load_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=HIST_COLS)
    h = pd.read_csv(path, dtype={"date": str, "tenor": str, "grade": str})
    h["value"] = pd.to_numeric(h["value"], errors="coerce")
    return h[HIST_COLS]


def upsert_history(hist: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """같은 (date, tenor, grade)는 최신 수집값으로 덮어씀 (KOFIA 사후 정정 반영)."""
    frames = [f for f in (hist, new) if not f.empty]
    if not frames:
        return pd.DataFrame(columns=HIST_COLS)
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["date", "tenor", "grade"], keep="last")
    return merged.sort_values(["tenor", "date", "grade"]).reset_index(drop=True)


def save_history(hist: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hist.to_csv(path, index=False, encoding="utf-8")


# ---------------------------------------------------------------- 지표 계산
def detect_value_mode(panel: pd.DataFrame) -> str:
    """KOFIA 원값이 '금리 수준'인지 '국고채 대비 스프레드'인지 판정.

    금리 수준이면 AAA 값이 국고채 값보다 크고 비슷한 크기(차이 < 국고채의 절반),
    스프레드면 등급 값이 국고채 금리보다 훨씬 작다.
    """
    if GOV not in panel or "AAA" not in panel:
        return "yield"
    g, a = panel[GOV].median(), panel["AAA"].median()
    return "yield" if a >= g and (a - g) < max(g, 0.5) else "spread"


def build_panels(hist: pd.DataFrame, tenor: str, mode: str = "auto"):
    """tenor 하나에 대해 (yields, credit_spread_bp, pickup_bp) 일자×등급 패널 반환."""
    h = hist[hist["tenor"] == str(tenor)]
    panel = h.pivot_table(index="date", columns="grade", values="value", aggfunc="last")
    panel.index = pd.to_datetime(panel.index, format="%Y%m%d")
    panel = panel.sort_index()
    grades = [g for g in GRADE_ORDER if g in panel.columns]

    if mode == "auto":
        mode = detect_value_mode(panel)
    if mode == "spread":              # 원값이 이미 국고 대비 스프레드(%p)
        spread = panel[grades] * 100
        yields = panel[grades].add(panel[GOV], axis=0)
    else:                             # 원값이 금리 수준(%)
        yields = panel[grades]
        spread = panel[grades].sub(panel[GOV], axis=0) * 100
    pickup = spread.sub(spread["AAA"], axis=0) if "AAA" in spread else spread * float("nan")
    yields = yields.assign(**{GOV: panel[GOV]})
    return yields, spread.round(1), pickup.round(1), mode


def _value_n_days_ago(s: pd.Series, days: int):
    s = s.dropna()
    if s.empty:
        return float("nan")
    cutoff = s.index[-1] - pd.Timedelta(days=days)
    past = s[s.index <= cutoff]
    return past.iloc[-1] if not past.empty else float("nan")


def percentile_rank(s: pd.Series, years: float) -> tuple[float, int]:
    """최근값이 과거 N년 분포에서 몇 %ile인지 (높을수록 스프레드 넓음)."""
    s = s.dropna()
    if s.empty:
        return float("nan"), 0
    win = s[s.index >= s.index[-1] - pd.DateOffset(years=years)]
    return round((win <= win.iloc[-1]).mean() * 100, 0), len(win)


def summary_table(spread: pd.DataFrame, pickup: pd.DataFrame, yields: pd.DataFrame,
                  pctl_years: float = 3.0, premium_bp: float = 0.0,
                  fee_band_bp: tuple[float, float] | None = None) -> pd.DataFrame:
    """최근 기준일 기준 등급별 요약 (메일 본문/엑셀 '요약' 시트)."""
    rows = []
    grades = [g for g in REFERENCE_GRADES[:1] + FOCUS_GRADES + REFERENCE_GRADES[1:]
              if g in spread.columns]
    for g in grades:
        sp, pk = spread[g], pickup[g]
        sp_pct, n = percentile_rank(sp, pctl_years)
        pk_pct, _ = percentile_rank(pk, pctl_years)
        net = pk.dropna().iloc[-1] - premium_bp if pk.notna().any() else float("nan")
        row = {
            "등급": g,
            "금리(%)": round(yields[g].dropna().iloc[-1], 3) if yields[g].notna().any() else None,
            "국고대비(bp)": sp.dropna().iloc[-1] if sp.notna().any() else None,
            "1주변동(bp)": round(sp.dropna().iloc[-1] - _value_n_days_ago(sp, 7), 1),
            "1개월변동(bp)": round(sp.dropna().iloc[-1] - _value_n_days_ago(sp, 30), 1),
            f"국고대비 {pctl_years:g}년 %ile": sp_pct,
            "AAA대비 보증차익(bp)": None if g == "AAA" else pk.dropna().iloc[-1],
            "보증차익 1개월변동(bp)": None if g == "AAA" else round(
                pk.dropna().iloc[-1] - _value_n_days_ago(pk, 30), 1),
            f"보증차익 {pctl_years:g}년 %ile": None if g == "AAA" else pk_pct,
            "순차익(bp, SGI프리미엄 차감)": None if g == "AAA" else round(net, 1),
            "표본(일)": n,
        }
        if fee_band_bp and g != "AAA":
            lo, hi = fee_band_bp
            row["보증료 대비"] = ("상단 초과" if net >= hi else
                               "밴드 내" if net >= lo else "하단 미만")
        rows.append(row)
    return pd.DataFrame(rows)


def signals(spread: pd.DataFrame, pickup: pd.DataFrame, pctl_years: float = 3.0,
            hot_pctl: float = 80, move_bp: float = 10) -> list[str]:
    """메일 상단에 띄울 알림 문구."""
    out = []
    for g in FOCUS_GRADES:
        if g not in pickup:
            continue
        pct, n = percentile_rank(pickup[g], pctl_years)
        if n >= 60 and pct >= hot_pctl:
            out.append(f"{g} 보증차익 {pickup[g].dropna().iloc[-1]:.0f}bp — "
                       f"{pctl_years:g}년 상위 {100 - pct:.0f}% (보증 수요 확대 국면)")
        wk = pickup[g].dropna().iloc[-1] - _value_n_days_ago(pickup[g], 7)
        if pd.notna(wk) and abs(wk) >= move_bp:
            out.append(f"{g} 보증차익 1주 {wk:+.0f}bp 급변")
    if {"A-", "BBB+"} <= set(spread.columns):
        gap = spread["BBB+"] - spread["A-"]
        m = gap.dropna().iloc[-1] - _value_n_days_ago(gap, 30)
        if pd.notna(m) and m >= move_bp:
            out.append(f"A- ↔ BBB+ 격차 1개월 {m:+.0f}bp 확대 (투자적격 하단 경색 신호)")
    return out
