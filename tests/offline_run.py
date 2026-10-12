"""KOFIA 접속 없이 전체 파이프라인을 돌려보는 오프라인 점검.

합성 XML(실제 응답 구조와 동일한 태그)로 fetch 를 대체하고 DRY_RUN=1 로 메일은 .eml 로만 저장.
    python tests/offline_run.py
"""
import os, sys, tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORKDIR = os.environ.get("OFFLINE_WORKDIR") or tempfile.mkdtemp(prefix="kofia_offline_")
os.makedirs(WORKDIR, exist_ok=True)
os.chdir(WORKDIR)
print(f"작업 폴더: {WORKDIR}")
os.environ.update(SENDER_EMAIL="test@example.com", SENDER_PW="x", RECIPIENTS="test@example.com",
                  DRY_RUN="1", BACKFILL_MONTHS=os.environ.get("BACKFILL_MONTHS", "36"),
                  FEE_BAND_BP=os.environ.get("FEE_BAND_BP", "30,70"),
                  HISTORY_PATH=os.environ.get("HISTORY_PATH", "data/spread_history_offline.csv"))

try:
    import exchange_calendars  # noqa: F401
except ImportError:          # 패키지 설치가 안 되는 환경용 최소 대체(주말만 휴장)
    import types
    class _Cal:
        def is_session(self, d): return pd.Timestamp(d).weekday() < 5
        def previous_session(self, d): return pd.Timestamp(d) - pd.offsets.BDay(1)
    sys.modules["exchange_calendars"] = types.SimpleNamespace(get_calendar=lambda _: _Cal())

import kofia_spread as ks  # noqa: E402

GRADES = ["AAA", "AA+", "AA0", "AA-", "A+", "A0", "A-", "BBB+", "BBB0", "BBB-"]
BASE_SP = [0.15, 0.20, 0.25, 0.30, 0.55, 0.75, 1.00, 2.50, 3.50, 5.00]   # %p
rng = np.random.default_rng(7)
DATES = pd.bdate_range("2023-01-02", "2026-10-11")
gov = 3.3 + np.cumsum(rng.normal(0, 0.01, len(DATES)))
stress = np.exp(-((np.arange(len(DATES)) - 600) / 60.0) ** 2)          # 중간에 경색 구간
SERIES = {g: gov + b * (1 + 0.8 * stress) + rng.normal(0, 0.01, len(DATES))
          for g, b in zip(GRADES, BASE_SP)}


class FakeSession:
    def get(self, *a, **k): return None


def fake_fetch(session, from_dt, to_dt, remain_cnt, bond_gb="7", wrk_gbn="TBOND_SPRD"):
    m = ET.Element("message")
    hdr = ET.SubElement(m, "BISSprdIdxListDTO")
    for g in GRADES:
        ET.SubElement(ET.SubElement(hdr, "BISSprdIdxDTO"), "bondGbCodeNm").text = g
    body = ET.SubElement(m, "BISSprdIdxBodyListDTO")
    sel = (DATES >= pd.Timestamp(from_dt)) & (DATES <= pd.Timestamp(to_dt))
    for i in np.where(sel)[0]:
        it = ET.SubElement(body, "BISSprdIdxDTO")
        ET.SubElement(it, "standardDt").text = DATES[i].strftime("%Y%m%d")
        ET.SubElement(it, "val1").text = f"{gov[i]:.3f}"
        for j, g in enumerate(GRADES, start=2):
            ET.SubElement(it, f"val{j}").text = f"{SERIES[g][i]:.3f}"
    return m


ks.fetch = fake_fetch
ks.requests.Session = FakeSession
ks.main()
