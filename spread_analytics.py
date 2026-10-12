"""회사채 신용스프레드 이력 누적 (data/spread_history.csv).

long format
    date   : 기준일 YYYYMMDD (str)
    tenor  : 잔존만기 코드 = KOFIA remainDayCnt (str, 예: "3" = 3개월물)
    grade  : "국고채" 또는 정규화된 등급명 (정부보증, AAA, AA+, AA, AA-, A+, A, A- ...)
    value  : KOFIA 원값 — 국고채는 금리(%), 등급은 국고 대비 스프레드(%p)
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

HISTORY_PATH = Path(os.getenv("HISTORY_PATH", "data/spread_history.csv"))
GOV = "국고채"
GRADE_ORDER = ["정부보증", "AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
               "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-"]
HIST_COLS = ["date", "tenor", "grade", "value"]


def normalize_grade(name: str) -> str:
    """KOFIA 등급명 표기 차이 흡수 (AA0→AA, A0→A, 공백 제거)."""
    n = (name or "").strip().replace(" ", "")
    up = n.upper()
    for base in ("AA", "A", "BBB", "BB"):
        if up == f"{base}0":
            return base
    return up if up.isascii() else n


def wide_to_long(df_wide: pd.DataFrame, tenor: str) -> pd.DataFrame:
    """parse_body() 결과(기준일, 국고채금리, 등급...) → long."""
    if df_wide is None or df_wide.empty:
        return pd.DataFrame(columns=HIST_COLS)
    d = df_wide.rename(columns={"기준일": "date", "국고채금리": GOV})
    d = d[d["date"].astype(str).str.fullmatch(r"\d{8}")]          # '차이' 등 요약행 제외
    long = d.melt(id_vars="date", var_name="grade", value_name="value")
    long["grade"] = long["grade"].map(lambda g: g if g == GOV else normalize_grade(g))
    long["tenor"] = str(tenor)
    long["date"] = long["date"].astype(str)
    return long.dropna(subset=["value"])[HIST_COLS]


def load_history(path: Path = HISTORY_PATH) -> pd.DataFrame:
    if not Path(path).exists():
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


def save_history(hist: pd.DataFrame, path: Path = HISTORY_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    hist.to_csv(path, index=False, encoding="utf-8")


def detect_value_mode(panel: pd.DataFrame) -> str:
    """등급 값이 '국고 대비 스프레드'인지 '금리 수준'인지 판정 (현재 KOFIA는 spread)."""
    if GOV not in panel or "AAA" not in panel:
        return "spread"
    g, a = panel[GOV].median(), panel["AAA"].median()
    return "yield" if a >= g and (a - g) < max(g, 0.5) else "spread"


def spread_panel_bp(hist: pd.DataFrame, tenor: str) -> tuple[pd.DataFrame, pd.Series]:
    """tenor 하나의 (일자 × 등급) 국고대비 스프레드(bp) 패널과 국고채 금리(%) 시계열."""
    h = hist[hist["tenor"] == str(tenor)]
    panel = h.pivot_table(index="date", columns="grade", values="value", aggfunc="last").sort_index()
    grades = [g for g in GRADE_ORDER if g in panel.columns]
    if os.getenv("VALUE_MODE", "auto") == "yield" or (
            os.getenv("VALUE_MODE", "auto") == "auto" and detect_value_mode(panel) == "yield"):
        sp = panel[grades].sub(panel[GOV], axis=0)
    else:
        sp = panel[grades]
    return (sp * 100).round(1), panel.get(GOV, pd.Series(dtype=float))
