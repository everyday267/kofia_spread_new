import os, smtplib, ssl, sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from html import escape
from pathlib import Path
from dateutil.relativedelta import relativedelta

import requests, pandas as pd, urllib3
import xml.etree.ElementTree as ET
import exchange_calendars as xcals

import spread_analytics as sa

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ===== 환경변수 =====
MONTHS       = int(os.getenv("MONTHS", "3"))            # 엑셀 원자료 시트 조회기간(개월)
BOND_GB      = os.getenv("BOND_GB", "7")                # 7 = 회사채
# KOFIA remainDayCnt 값 목록(콤마). 기본값 = MONTHS → 기존과 동일한 요청.
# 화면의 '잔존만기' 선택값에 해당하는지 검증 후 "3,12,36" 처럼 확장 (README §잔존만기 검증)
REMAIN_CNTS  = [x.strip() for x in os.getenv("REMAIN_DAY_CNT", str(MONTHS)).split(",") if x.strip()]
BACKFILL_MONTHS = int(os.getenv("BACKFILL_MONTHS", "0") or 0)   # >0 이면 과거 이력 일괄 적재
CHART_MONTHS = int(os.getenv("CHART_MONTHS", "24"))     # 차트 표시 기간
PCTL_YEARS   = float(os.getenv("PCTL_YEARS", "3"))      # 백분위 산출 창(년)
SGI_PREMIUM_BP = float(os.getenv("SGI_PREMIUM_BP", "0"))  # SGI 보증물이 순수 AAA 대비 더 받는 금리(bp)
_fee = [x for x in os.getenv("FEE_BAND_BP", "").split(",") if x.strip()]
FEE_BAND_BP  = (float(_fee[0]), float(_fee[1])) if len(_fee) == 2 else None   # 예: "40,80"
VALUE_MODE   = os.getenv("VALUE_MODE", "auto")          # auto / yield / spread
HISTORY_PATH = Path(os.getenv("HISTORY_PATH", "data/spread_history.csv"))
SMTP_HOST    = "smtp.gmail.com"
SMTP_PORT    = 587

OUT_DIR = Path("output")

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


def fetch(session, from_dt, to_dt, remain_cnt, bond_gb="7", wrk_gbn="TBOND_SPRD"):
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
    <remainDayCnt>{remain_cnt}</remainDayCnt>
    <bondGbCode>{bond_gb}</bondGbCode>
    <standardDt>{from_dt}</standardDt>
    <uStandardDt>{to_dt}</uStandardDt>
  </BISSprdIdxDTO>
</message>"""
    r = session.post(URL, data=body.encode("utf-8"), headers=HEADERS, timeout=30)
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


def collect(session, to_dt, months, remain_cnt, chunk_months=12):
    """months 기간을 chunk_months 단위로 나눠 조회 (장기 백필 시 응답 크기 제한 대비)."""
    end = datetime.strptime(to_dt, "%Y%m%d")
    start = end - relativedelta(months=months)
    frames, ratings = [], []
    cur_end = end
    while cur_end > start:
        cur_start = max(start, cur_end - relativedelta(months=chunk_months))
        root = fetch(session, cur_start.strftime("%Y%m%d"), cur_end.strftime("%Y%m%d"),
                     remain_cnt, BOND_GB)
        ratings = parse_ratings(root) or ratings
        part = parse_body(root, ratings)
        if not part.empty:
            frames.append(part)
        cur_end = cur_start - timedelta(days=1)
    if not frames:
        return pd.DataFrame(), ratings
    df = pd.concat(frames).drop_duplicates("기준일", keep="first")
    return df.sort_values("기준일", ascending=False).reset_index(drop=True), ratings


def tenor_label(code: str) -> str:
    m = int(code)
    return f"{m}M" if m < 12 or m % 12 else f"{m // 12}Y"


# ============ 메일 ============
def df_to_html(df: pd.DataFrame) -> str:
    th = "".join(f"<th style='padding:4px 8px;border-bottom:1px solid #ccc;text-align:right'>"
                 f"{escape(str(c))}</th>" for c in df.columns)
    trs = []
    for _, r in df.iterrows():
        tds = "".join(
            f"<td style='padding:4px 8px;text-align:right'>"
            f"{'' if pd.isna(v) else escape(str(v))}</td>" for v in r.values)
        trs.append(f"<tr>{tds}</tr>")
    return (f"<table style='border-collapse:collapse;font-size:12px;font-family:sans-serif'>"
            f"<tr>{th}</tr>{''.join(trs)}</table>")


def send_via_gmail(host, port, sender, pw, msg):
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as srv:
        srv.ehlo(); srv.starttls(context=ctx); srv.ehlo()
        srv.login(sender, pw)
        srv.send_message(msg)
    return f"{port}/STARTTLS"


def main():
    sender_email = os.environ["SENDER_EMAIL"]
    sender_pw    = os.environ["SENDER_PW"]
    recipients   = [x.strip() for x in os.environ["RECIPIENTS"].split(",") if x.strip()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 기준일 ---- (kofia.yml Job 1 과 동일 로직 유지 — PRD §9-1)
    kst  = timezone(timedelta(hours=9))
    xkrx = xcals.get_calendar("XKRX")
    today = pd.Timestamp(datetime.now(kst).date())
    if not xkrx.is_session(today):
        print(f"{today.date()} 비영업일 - 종료")
        sys.exit(0)
    to_dt = xkrx.previous_session(today).date().strftime("%Y%m%d")
    print(f"기준 영업일: {to_dt}")

    s = requests.Session()
    s.get(REFERER, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=15)

    # ---- 수집 + 이력 누적 ----
    hist = sa.load_history(HISTORY_PATH)
    print(f"이력 로드: {len(hist)}행 ({HISTORY_PATH})")
    raw_by_tenor = {}
    for cnt in REMAIN_CNTS:
        months = max(MONTHS, BACKFILL_MONTHS)
        df, ratings = collect(s, to_dt, months, cnt)
        print(f"[remainDayCnt={cnt}] 등급: {ratings} / {len(df)}행")
        if df.empty:
            continue
        raw_by_tenor[cnt] = df
        hist = sa.upsert_history(hist, sa.wide_to_long(df, cnt))
    if not raw_by_tenor:
        sys.exit("수집 0행 — 응답 비어있음 (해외 IP 차단 가능성)")
    sa.save_history(hist, HISTORY_PATH)
    print(f"이력 저장: {len(hist)}행 → {HISTORY_PATH}")

    # ---- 지표·차트 ----
    from spread_charts import chart_credit_spread, chart_pickup
    summaries, charts, alerts, sheets = {}, [], [], {}
    chart_from = pd.Timestamp(to_dt) - pd.DateOffset(months=CHART_MONTHS)
    for cnt in raw_by_tenor:
        lbl = tenor_label(cnt)
        yields, spread, pickup, mode = sa.build_panels(hist, cnt, VALUE_MODE)
        print(f"[{lbl}] 값 해석 모드: {mode} / 이력 {len(spread)}일")
        summaries[lbl] = sa.summary_table(spread, pickup, yields, PCTL_YEARS,
                                          SGI_PREMIUM_BP, FEE_BAND_BP)
        alerts += [f"[{lbl}] {a}" for a in sa.signals(spread, pickup, PCTL_YEARS)]
        sp_c, pk_c = spread[spread.index >= chart_from], pickup[pickup.index >= chart_from]
        charts.append(chart_credit_spread(sp_c, lbl, OUT_DIR / f"chart_spread_{lbl}_{to_dt}.png"))
        charts.append(chart_pickup(pk_c, lbl, OUT_DIR / f"chart_pickup_{lbl}_{to_dt}.png",
                                   FEE_BAND_BP, SGI_PREMIUM_BP))
        sheets[f"국고대비bp_{lbl}"] = spread.sort_index(ascending=False)
        sheets[f"보증차익bp_{lbl}"] = pickup.drop(columns="AAA", errors="ignore").sort_index(ascending=False)

    # ---- 엑셀 ---- (파일명 패턴 유지 — PRD §9-7)
    out_path = OUT_DIR / f"kofia_corp_spread_{to_dt}.xlsx"
    with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
        first = next(iter(raw_by_tenor))
        raw_by_tenor[first].head(400).to_excel(xw, sheet_name="회사채_신용스프레드", index=False)
        for lbl, sm in summaries.items():
            sm.to_excel(xw, sheet_name=f"요약_{lbl}", index=False)
        for name, d in sheets.items():
            d.index = d.index.strftime("%Y-%m-%d")
            d.to_excel(xw, sheet_name=name[:31], index_label="기준일")
    print(f"저장: {out_path}")

    # ---- 메일 ----
    msg = EmailMessage()
    msg["Subject"] = f"[KOFIA] 회사채 신용스프레드 · ABS보증 차익 {to_dt}"
    msg["From"]    = sender_email
    msg["To"]      = ", ".join(recipients)
    text = [f"기준 영업일: {to_dt}", *alerts] + [f"\n[{k}]\n{v.to_string(index=False)}"
                                               for k, v in summaries.items()]
    msg.set_content("\n".join(text))

    cids = [make_msgid(domain="kofia.local") for _ in charts]
    alert_html = ("<ul>" + "".join(f"<li>{escape(a)}</li>" for a in alerts) + "</ul>"
                  if alerts else "<p style='color:#52514e'>특이 신호 없음</p>")
    tables = "".join(f"<h3 style='font-family:sans-serif'>요약 ({escape(k)})</h3>{df_to_html(v)}"
                     for k, v in summaries.items())
    imgs = "".join(f"<p><img src='cid:{c[1:-1]}' style='max-width:100%'></p>" for c in cids)
    note = ("<p style='font-size:11px;color:#52514e'>보증차익 = 무보증 등급 스프레드 − AAA 스프레드 "
            f"(동일 만기). 순차익 = 보증차익 − SGI보증물 프리미엄({SGI_PREMIUM_BP:g}bp). "
            f"%ile = 최근 {PCTL_YEARS:g}년 분포 내 위치(높을수록 넓음).</p>")
    msg.add_alternative(f"<html><body><h2 style='font-family:sans-serif'>회사채 신용스프레드 · "
                        f"ABS보증 차익 ({to_dt})</h2>{alert_html}{tables}{note}{imgs}</body></html>",
                        subtype="html")
    html_part = msg.get_payload()[-1]
    for cid, path in zip(cids, charts):
        html_part.add_related(path.read_bytes(), maintype="image", subtype="png", cid=cid)
    with open(out_path, "rb") as f:
        msg.add_attachment(
            f.read(), maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=out_path.name,
        )

    if os.getenv("DRY_RUN") == "1":
        (OUT_DIR / f"mail_preview_{to_dt}.eml").write_bytes(bytes(msg))
        print("DRY_RUN — 메일 미발송, .eml 저장"); return
    try:
        mode = send_via_gmail(SMTP_HOST, SMTP_PORT, sender_email,
                              sender_pw.replace(" ", ""), msg)
        print(f"메일 발송 완료 ({SMTP_HOST}, {mode}) → {recipients}")
    except smtplib.SMTPAuthenticationError as e:
        detail = e.smtp_error.decode("utf-8", "replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        print(f"인증 실패: Gmail 앱 비밀번호 16자리 확인 (서버 응답: {e.smtp_code} {detail})"); sys.exit(1)
    except Exception as e:
        print(f"메일 발송 실패: {type(e).__name__}: {e}"); sys.exit(1)


if __name__ == "__main__":
    main()
