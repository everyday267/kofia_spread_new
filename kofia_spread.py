import os, smtplib, ssl, sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from dateutil.relativedelta import relativedelta

import requests, pandas as pd, urllib3
import xml.etree.ElementTree as ET
import exchange_calendars as xcals

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)



# ===== 환경변수 =====
MONTHS       = int(os.getenv("MONTHS", "3"))
BOND_GB      = os.getenv("BOND_GB", "7")
SENDER_EMAIL = os.environ["SENDER_EMAIL"]
SENDER_PW    = os.environ["SENDER_PW"]
RECIPIENTS   = [x.strip() for x in os.environ["RECIPIENTS"].split(",") if x.strip()]
SMTP_HOST    = "smtp.gmail.com"
SMTP_PORT    = 587

OUT_DIR = Path("output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- 기준일 ----
KST  = timezone(timedelta(hours=9))
xkrx = xcals.get_calendar("XKRX")
today = pd.Timestamp(datetime.now(KST).date())
if not xkrx.is_session(today):
    print(f"{today.date()} 비영업일 - 종료")
    sys.exit(0)   
TO_DT = xkrx.previous_session(today).date().strftime("%Y%m%d")
print(f"기준 영업일: {TO_DT}")

# ---- KOFIA ----
BASE = "https://www.kofiabond.or.kr"
URL  = f"{BASE}/proframeWeb/XMLSERVICES/"
REFERER = (f"{BASE}/websquare/websquare.html?"
           "w2xPath=/xml/marketidx/mndmktidx/BISCdtBndTyp.xml"
           "&divisionId=MBIS01060010030010&topMenuIndex=6")
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Referer": REFERER, "Origin": BASE, "X-Requested-With": "XMLHttpRequest",
}

s = requests.Session()
s.get(REFERER, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15)

def fetch(to_dt, months, bond_gb="7", wrk_gbn="TBOND_SPRD"):
    from_dt = (datetime.strptime(to_dt, "%Y%m%d") - relativedelta(months=months)).strftime("%Y%m%d")
    body = f"""<?xml version="1.0" encoding="utf-8"?>
<message>
  <proframeHeader>
    <pfmAppName>BIS-KOFIABOND</pfmAppName>
    <pfmSvcName>BISCdtRnkSprdIdxSrchSO</pfmSvcName>
    <pfmFnName>selectCdtBndIdxList</pfmFnName>
  </proframeHeader>
  <systemHeader></systemHeader>
  <BISSprdIdxDTO>
    <wrkGbn>{wrk_gbn}</wrkGbn>
    <remainDayCnt>{months}</remainDayCnt>
    <bondGbCode>{bond_gb}</bondGbCode>
    <standardDt>{from_dt}</standardDt>
    <uStandardDt>{to_dt}</uStandardDt>
  </BISSprdIdxDTO>
</message>"""
    r = s.post(URL, data=body.encode("utf-8"), headers=HEADERS, timeout=30)
    r.encoding = "utf-8"; r.raise_for_status()
    return ET.fromstring(r.text)

def parse_ratings(root):
    names = []
    hdr = root.find(".//BISSprdIdxListDTO")
    if hdr is None: return names
    for item in hdr.findall("BISSprdIdxDTO"):
        nm = (item.findtext("bondGbCodeNm") or "").strip()
        if nm: names.append(nm)
    return names

def parse_body(root, rating_names):
    rows = []
    body = root.find(".//BISSprdIdxBodyListDTO")
    if body is None: return pd.DataFrame()
    for item in body.findall("BISSprdIdxDTO"):
        std = (item.findtext("standardDt") or "").strip()
        if not std: continue
        row = {"기준일": std,
               "국고채금리": pd.to_numeric((item.findtext("val1") or "").strip(), errors="coerce")}
        for i, name in enumerate(rating_names, start=2):
            row[name] = pd.to_numeric((item.findtext(f"val{i}") or "").strip(), errors="coerce")
        rows.append(row)
    df = pd.DataFrame(rows)
    return df.sort_values("기준일", ascending=False).reset_index(drop=True) if not df.empty else df

root = fetch(TO_DT, MONTHS, BOND_GB)
ratings = parse_ratings(root)
df = parse_body(root, ratings)
print(f"등급: {ratings} / {len(df)}행")

if df.empty:
    sys.exit("수집 0행 — 응답 비어있음 (해외 IP 차단 가능성)")

out_path = OUT_DIR / f"kofia_corp_spread_{TO_DT}.xlsx"
with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
    df.to_excel(xw, sheet_name="회사채_신용스프레드", index=False)
print(f"저장: {out_path}")

# ============ Gmail 발송 ============
def send_via_gmail(host, port, sender, pw, recipients, msg):
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as srv:
        srv.ehlo(); srv.starttls(context=ctx); srv.ehlo()
        srv.login(sender, pw)
        srv.send_message(msg)
    return f"{port}/STARTTLS"

msg = EmailMessage()
msg["Subject"] = f"[KOFIA] 회사채 신용스프레드 {TO_DT} ({MONTHS}개월)"
msg["From"]    = SENDER_EMAIL
msg["To"]      = ", ".join(RECIPIENTS)
msg.set_content(
    f"KOFIA 채권정보센터 회사채 신용스프레드 자동 수집 결과입니다.\n"
    f"기준 영업일: {TO_DT}\n조회기간: {MONTHS}개월\n수집: {len(df)}행"
)
with open(out_path, "rb") as f:
    msg.add_attachment(
        f.read(), maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=out_path.name,
    )
try:
    mode = send_via_gmail(SMTP_HOST, SMTP_PORT, SENDER_EMAIL,
                          SENDER_PW.replace(" ", ""), RECIPIENTS, msg)
    print(f"메일 발송 완료 ({SMTP_HOST}, {mode}) → {RECIPIENTS}")
except smtplib.SMTPAuthenticationError as e:
    detail = e.smtp_error.decode("utf-8", "replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
    print(f"인증 실패: Gmail 앱 비밀번호 16자리 확인 (서버 응답: {e.smtp_code} {detail})"); sys.exit(1)
except Exception as e:
    print(f"메일 발송 실패: {type(e).__name__}: {e}"); sys.exit(1)
