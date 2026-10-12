"""data/spread_history.csv → docs/index.html (자체 완결형 인터랙티브 대시보드).

외부 CDN/라이브러리 없이 데이터(JSON)를 HTML에 내장하므로, 파일 하나만 열어도 동작한다.
GitHub Pages(Settings → Pages → main /docs)로 켜면 https://<owner>.github.io/<repo>/ 에서 바로 열람.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import spread_analytics as sa

TEMPLATE = Path(__file__).with_name("dashboard_template.html")
DASHBOARD_PATH = Path(os.getenv("DASHBOARD_PATH", "docs/index.html"))


def tenor_label(code: str) -> str:
    """remainDayCnt(개월) → 화면 표기 (3→3개월, 12→1년, 18→1년6개월)."""
    try:
        m = int(code)
    except ValueError:
        return str(code)
    y, r = divmod(m, 12)
    return f"{m}개월" if y == 0 else f"{y}년" + (f"{r}개월" if r else "")


def _clean(values) -> list:
    return [None if pd.isna(v) else round(float(v), 3) for v in values]


def build_payload(hist: pd.DataFrame, as_of: str) -> dict:
    tenors = []
    codes = sorted(hist["tenor"].dropna().unique(), key=lambda c: (len(c), c))
    for code in codes:
        sp, gov = sa.spread_panel_bp(hist, code)
        if sp.empty:
            continue
        tenors.append({
            "code": code,
            "label": tenor_label(code),
            "dates": list(sp.index),
            "gov": _clean(gov.reindex(sp.index).values),
            "s": {g: _clean(sp[g].values) for g in sp.columns},
        })
    built = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    return {"asOf": as_of, "built": built, "tenors": tenors}


def build_dashboard(hist: pd.DataFrame, as_of: str, out: Path = DASHBOARD_PATH) -> Path:
    payload = json.dumps(build_payload(hist, as_of), ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")          # <script> 안전 삽입
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":       # 이력 CSV만으로 대시보드 재생성
    h = sa.load_history()
    print(build_dashboard(h, h["date"].max()))
