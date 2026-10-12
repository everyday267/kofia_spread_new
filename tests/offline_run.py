"""KOFIA 접속·메일 발송 없이 kofia_spread.py 전체를 실행해 보는 오프라인 점검.

- requests.Session  → 합성 XML 응답 (실제와 같은 태그 구조: 기준일 YYYY-MM-DD, val1=국고 금리 %, val2~ = 등급 스프레드 %p)
- smtplib.SMTP      → 발송 대신 output/mail_preview.eml 저장
- exchange_calendars 미설치 환경이면 주말만 휴장으로 대체

    python tests/offline_run.py                    # 임시 폴더에서 실행
    BACKFILL_MONTHS=36 python tests/offline_run.py # 백필 경로 점검
"""
import os, re, runpy, sys, tempfile, types
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
os.environ.setdefault("SENDER_EMAIL", "test@example.com")
os.environ.setdefault("SENDER_PW", "x")
os.environ.setdefault("RECIPIENTS", "test@example.com")
os.environ.setdefault("HISTORY_TENORS", "3,12,36")

try:
    import exchange_calendars  # noqa: F401
except ImportError:
    class _Cal:
        def is_session(self, d): return pd.Timestamp(d).weekday() < 5
        def previous_session(self, d): return pd.Timestamp(d) - pd.offsets.BDay(1)
    sys.modules["exchange_calendars"] = types.SimpleNamespace(get_calendar=lambda _: _Cal())

# ---------- 합성 시장 ----------
# 실제 회사채(bondGbCode=7) 응답과 같은 등급 구성 (2026-10-12 확인)
GRADES = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"]
BASE = [0.29, 0.38, 0.41, 0.44, 0.53, 0.63, 0.86, 1.20, 1.59, 2.27]
rng = np.random.default_rng(7)
DATES = pd.bdate_range("2021-01-04", "2026-10-11")
gov3 = 3.0 + np.cumsum(rng.normal(0, 0.008, len(DATES)))
stress = np.exp(-((np.arange(len(DATES)) - 470) / 50.0) ** 2)      # 2022.10 경색 흉내
noise = {g: rng.normal(0, 0.008, len(DATES)) for g in GRADES}


def series(tenor):
    k = 1 + 0.15 * np.log(int(tenor) / 3)                          # 만기 길수록 스프레드↑
    gov = gov3 + 0.08 * np.log(int(tenor) / 3)
    return gov, {g: (b * k) * (1 + 1.2 * stress) + noise[g] for g, b in zip(GRADES, BASE)}


class FakeResp:
    def __init__(self, text): self.text, self.encoding = text, "utf-8"
    def raise_for_status(self): pass


class FakeSession:
    def get(self, *a, **k): return None
    def post(self, url, data=None, **k):
        body = data.decode("utf-8")
        tag = lambda t: re.search(f"<{t}>(.*?)</{t}>", body).group(1)
        f, t, tenor = pd.Timestamp(tag("standardDt")), pd.Timestamp(tag("uStandardDt")), tag("remainDayCnt")
        gov, ser = series(tenor)
        m = ET.Element("message")
        hdr = ET.SubElement(m, "BISSprdIdxListDTO")
        for g in GRADES:
            ET.SubElement(ET.SubElement(hdr, "BISSprdIdxDTO"), "bondGbCodeNm").text = g
        b = ET.SubElement(m, "BISSprdIdxBodyListDTO")
        for i in np.where((DATES >= f) & (DATES <= t))[0][::-1]:
            it = ET.SubElement(b, "BISSprdIdxDTO")
            ET.SubElement(it, "standardDt").text = DATES[i].strftime("%Y-%m-%d")   # 실제 응답 형식
            ET.SubElement(it, "val1").text = f"{gov[i]:.3f}"
            for j, g in enumerate(GRADES, start=2):
                ET.SubElement(it, f"val{j}").text = f"{ser[g][i]:.2f}"
            for j in range(len(GRADES) + 2, 21):                     # 실제 응답처럼 빈 val 칸
                ET.SubElement(it, f"val{j}").text = ""
        return FakeResp(ET.tostring(m, encoding="unicode"))


class FakeSMTP:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def ehlo(self): pass
    def starttls(self, **k): pass
    def login(self, *a): pass
    def send_message(self, msg):
        Path("output/mail_preview.eml").write_bytes(bytes(msg))
        print(f"[FakeSMTP] 메일 저장: output/mail_preview.eml (첨부 {len(list(msg.iter_attachments()))}개)")


import requests, smtplib  # noqa: E402
requests.Session = FakeSession
smtplib.SMTP = FakeSMTP
runpy.run_path(str(ROOT / "kofia_spread.py"), run_name="__main__")
