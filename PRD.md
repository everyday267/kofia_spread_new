# PRD — KOFIA 회사채 신용스프레드 자동 수집·발송 시스템

> **문서 목적**: 이 문서는 사람뿐 아니라 **AI 어시스턴트가 읽고 즉시 트러블슈팅·기능 수정을 수행할 수 있도록** 작성된 제품 요구사항 + 기술 명세 + 운영 플레이북입니다.
> 코드 수정 전 반드시 [§9 수정 시 지켜야 할 불변조건](#9-수정-시-지켜야-할-불변조건-invariants)을 확인하세요.

- **문서 버전**: 1.0 (2026-07-05)
- **대상 코드 버전**: v1.2 + 월요일 버그 수정 커밋(`7463172`) 반영 상태
- **저장소**: `everyday267/kofia_spread_new`

---

## 1. 제품 개요

### 1.1 한 줄 요약

KOFIA 채권정보센터(BIS)에서 **회사채 신용등급별 스프레드**(국고채 대비)를 매 영업일 아침 자동 조회하여 Excel(.xlsx)로 저장하고, 지정 수신자에게 Gmail로 발송하는 **GitHub Actions 기반 무인 자동화 파이프라인**.

### 1.2 해결하는 문제

- 채권 실무자가 매일 아침 KOFIA 사이트에 접속해 스프레드를 수동 조회·정리하는 반복 작업 제거
- 별도 서버 없이 GitHub Actions 무료 러너만으로 운영 (인프라 비용 0원)

### 1.3 목표 (Goals)

| # | 목표 | 성공 기준 |
|---|---|---|
| G1 | 매 KRX 영업일 아침 자동 실행 | KST 06:23 cron 트리거 (러너 지연 감안 시 ~07:00 내 수신) |
| G2 | 직전 영업일 기준 스프레드 데이터 수집 | 최근 N개월(기본 3개월) 일별 데이터, 등급 전 컬럼 포함 |
| G3 | Excel 첨부 메일 발송 | 수신자 전원에게 xlsx 첨부 메일 도착 |
| G4 | 비영업일 자동 스킵 | 주말·공휴일에는 메일 미발송, 워크플로우는 성공 처리 |
| G5 | 결과물 보존 | Actions Artifact 30일 보관 |

### 1.4 비목표 (Non-Goals)

- 실시간/장중 데이터 수집 (일 1회 배치만)
- 데이터베이스 적재, 시계열 누적 저장 (매회 독립 파일 생성)
- 실패 시 자동 재시도 (다음 영업일 스케줄까지 대기)
- 회사채 외 다른 지표의 기본 수집 (환경변수로 확장은 가능)

### 1.5 사용자

- **주 사용자**: 메일 수신자(채권 실무자). 코드를 만지지 않음.
- **운영자**: 레포 소유자. Secrets 관리, 워크플로우 수동 실행, 장애 대응.
- **유지보수자**: 사람 또는 AI. 이 문서를 근거로 코드 수정.

---

## 2. 폴더 구조 및 파일별 역할

```
kofia_spread_new/
├── kofia_spread.py            # 본체: 영업일 체크 → KOFIA 조회 → XML 파싱 → xlsx 저장 → Gmail 발송
├── requirements.txt           # Python 의존성 (버전 미고정, 항상 최신 설치)
├── README.md                  # 사용자용 안내 문서
├── PRD.md                     # (본 문서) AI/유지보수자용 명세
└── .github/
    └── workflows/
        └── kofia.yml          # GitHub Actions: cron 스케줄, 영업일 사전 체크, 실행, Artifact 업로드
```

파일이 단 4개뿐인 **단일 스크립트 프로젝트**입니다. 로직 수정은 사실상 `kofia_spread.py`와 `kofia.yml` 두 파일에서만 발생합니다.

---

## 3. 시스템 아키텍처 / 동작 흐름

```
[GitHub Actions cron: UTC 21:23 일~목 = KST 06:23 월~금]
        │
        ▼
┌─ Job 1: check-businessday ─────────────────────────┐
│  exchange_calendars XKRX 로 "오늘(KST)"이           │
│  KRX 영업일인지 판정 → output: is_open=true/false   │
└────────────────────────────────────────────────────┘
        │  is_open == 'true'  또는 workflow_dispatch(수동 실행)일 때만
        ▼
┌─ Job 2: run ───────────────────────────────────────┐
│  1. checkout + Python 3.11 + pip install           │
│  2. python kofia_spread.py                         │
│     ├─ (a) 영업일 재체크: 비영업일이면 exit 0       │
│     ├─ (b) TO_DT = 직전 KRX 영업일 (YYYYMMDD)      │
│     ├─ (c) KOFIA 세션 워밍업(GET Referer 페이지)    │
│     ├─ (d) POST XML → 응답 파싱(등급명 + 일별수치)  │
│     ├─ (e) output/kofia_corp_spread_{TO_DT}.xlsx   │
│     └─ (f) Gmail SMTP 587 STARTTLS 발송            │
│  3. Artifact 업로드 (if: always(), 30일 보관)       │
└────────────────────────────────────────────────────┘
```

**영업일 체크가 2중**으로 되어 있음에 주의:

1. **워크플로우 레벨** (`kofia.yml` Job 1): 비영업일이면 Job 2 자체를 skip → Actions 실행 시간 절약, 실행 이력이 "skipped"로 명확히 표시.
2. **스크립트 레벨** (`kofia_spread.py:31-33`): 수동 실행(workflow_dispatch)이 비영업일에 눌렸을 때의 안전망. `sys.exit(0)`으로 조용히 성공 종료.

> ⚠️ 두 체크는 **의도된 중복**입니다. 하나를 제거하지 마세요. 단, 로직을 바꿀 땐 **양쪽을 동일하게** 바꿔야 합니다 (과거 두 로직이 달라서 월요일 미발송 버그 발생 — §7.1 참고).

---

## 4. 상세 기술 명세

### 4.1 환경변수 (kofia_spread.py 입력)

| 변수 | 필수 | 기본값 | 설명 | 정의 위치 |
|---|---|---|---|---|
| `MONTHS` | 아니오 | `"3"` | 조회 기간(개월). KOFIA UI 기준 1/3/6/12 사용 | `kofia.yml` env |
| `BOND_GB` | 아니오 | `"7"` | 채권 구분 코드. `7` = 회사채 | `kofia.yml` env |
| `SENDER_EMAIL` | **예** | — | 발신 Gmail 주소 | Secret `GMAIL_SENDER` |
| `SENDER_PW` | **예** | — | Gmail **앱 비밀번호** 16자리 (공백 있어도 코드가 제거함) | Secret `GMAIL_APP_PW` |
| `RECIPIENTS` | **예** | — | 콤마 구분 수신자 목록 | Secret `MAIL_RECIPIENTS` |

- 필수 변수 누락 시 `os.environ[...]`에서 **`KeyError`로 즉시 크래시** (traceback에 변수명 표시됨).
- `RECIPIENTS`는 콤마 분리 후 공백 항목 제거. 전부 공백이면 빈 리스트가 되어 발송 단계에서 실패.

### 4.2 기준일 결정 로직 (`kofia_spread.py:27-35`)

```python
KST  = timezone(timedelta(hours=9))
xkrx = xcals.get_calendar("XKRX")
today = pd.Timestamp(datetime.now(KST).date())
if not xkrx.is_session(today):
    sys.exit(0)                                # 비영업일 → 성공 종료
TO_DT = xkrx.previous_session(today).date().strftime("%Y%m%d")
```

- 러너는 UTC지만 `datetime.now(KST)`로 한국 날짜를 얻으므로 시간대 문제 없음.
- **오늘이 영업일일 때만 실행**하고, 데이터 기준일은 **직전 영업일**(`previous_session`). 월요일 실행 시 기준일은 지난 금요일(그 사이 공휴일이 있으면 그 이전 영업일).
- `exchange_calendars`의 XKRX 캘린더가 한국 공휴일 정보의 유일한 소스 → **임시공휴일·대체공휴일 대응은 패키지 업데이트에 의존** (§7.4).

### 4.3 KOFIA API 계약 (비공식 — 언제든 변경될 수 있음)

| 항목 | 값 |
|---|---|
| 엔드포인트 | `POST https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/` |
| 서비스 | `pfmSvcName=BISCdtRnkSprdIdxSrchSO`, `pfmFnName=selectCdtBndIdxList` |
| 사전 요청 | 세션 쿠키 확보를 위해 Referer 페이지 GET 1회 (`kofia_spread.py:49-50`) |
| 필수 헤더 | `Content-Type: application/x-www-form-urlencoded; charset=UTF-8`, `Referer`, `Origin`, `X-Requested-With: XMLHttpRequest`, 브라우저형 `User-Agent` |

**요청 바디** (XML, `fetch()` 함수):

```xml
<BISSprdIdxDTO>
  <wrkGbn>TBOND_SPRD</wrkGbn>          <!-- 국고채 대비 스프레드 -->
  <remainDayCnt>{months}</remainDayCnt> <!-- ⚠️ 필드명과 달리 '개월 수'가 들어감. KOFIA 웹 UI가 이렇게 보냄 -->
  <bondGbCode>{bond_gb}</bondGbCode>    <!-- 7=회사채 -->
  <standardDt>{from_dt}</standardDt>    <!-- 조회 시작일 = to_dt - months -->
  <uStandardDt>{to_dt}</uStandardDt>    <!-- 조회 종료일 = 직전 영업일 -->
</BISSprdIdxDTO>
```

**응답 구조와 파싱 규칙** — 여기가 가장 깨지기 쉬운 부분:

```
<message>
  ├─ BISSprdIdxListDTO          ← "헤더": 등급명 목록
  │    └─ BISSprdIdxDTO (반복)
  │         └─ bondGbCodeNm     ← 예: "AAA", "AA+", ...
  └─ BISSprdIdxBodyListDTO      ← "바디": 일자별 수치
       └─ BISSprdIdxDTO (반복)
            ├─ standardDt       ← 기준일 YYYYMMDD
            ├─ val1             ← 국고채금리
            ├─ val2             ← 헤더 1번째 등급 값
            ├─ val3             ← 헤더 2번째 등급 값
            └─ ...              ← valN = 헤더 (N-1)번째 등급 값
```

- **핵심 가정**: `val1`은 국고채금리 고정, `val2`부터는 **헤더의 등급명 등장 순서와 1:1 대응** (`parse_body()`의 `enumerate(rating_names, start=2)`). KOFIA가 컬럼 순서나 개수를 바꾸면 **에러 없이 값이 어긋난 엑셀**이 나올 수 있음 — 데이터가 이상하다는 제보가 오면 이 매핑부터 의심할 것.
- 숫자 변환은 `pd.to_numeric(errors="coerce")` → 빈 값/이상값은 NaN 처리 (크래시 없음).
- 바디가 아예 없으면 빈 DataFrame → `수집 0행` 메시지와 함께 exit 1 (`kofia_spread.py:103-104`).

### 4.4 Excel 출력

- 경로: `output/kofia_corp_spread_{TO_DT}.xlsx`, 시트명 `회사채_신용스프레드`, 엔진 openpyxl.
- 컬럼: `기준일`, `국고채금리`, 이후 KOFIA 응답의 `bondGbCodeNm` 그대로 (AAA, AA+, …).
- 기준일 **내림차순** (최신이 첫 행). 단위: %.

### 4.5 메일 발송 (`send_via_gmail`, `kofia_spread.py:111-141`)

- `smtp.gmail.com:587` STARTTLS + 로그인 (`ssl.create_default_context()`).
- 앱 비밀번호의 공백은 `SENDER_PW.replace(" ", "")`로 자동 제거 — Secrets에 공백 포함 복붙해도 동작.
- 제목: `[KOFIA] 회사채 신용스프레드 {TO_DT} ({MONTHS}개월)`.
- `SMTPAuthenticationError` → "앱 비밀번호 확인" 메시지 + exit 1. 기타 예외 → 타입/메시지 출력 + exit 1.

### 4.6 종료 코드 의미 (Actions 결과 해석 기준)

| exit code | 의미 | Actions 표시 |
|---|---|---|
| 0 | 성공 발송 **또는** 비영업일 정상 스킵 | ✅ success |
| 1 | 수집 0행 / SMTP 인증 실패 / 발송 실패 | ❌ failure |
| (traceback) | 필수 환경변수 누락, 네트워크 예외, XML 파싱 실패 등 | ❌ failure |

### 4.7 GitHub Actions 워크플로우 (`kofia.yml`)

- **cron**: `"23 21 * * 0-4"` = UTC 일~목 21:23 = **KST 월~금 06:23**. GitHub cron은 UTC 기준이므로 KST 평일 아침은 **요일값 `0-4`** 를 써야 함 (`1-5`는 KST 화~토가 됨).
- **Job 1 `check-businessday`**: 인라인 Python(heredoc)으로 `xkrx.is_session(today)` 판정 → `GITHUB_OUTPUT`에 `is_open` 기록. 의존성은 `exchange_calendars pandas`만 설치.
- **Job 2 `run` 실행 조건**: `is_open == 'true' || github.event_name == 'workflow_dispatch'` — **수동 실행은 영업일 체크를 우회**하지만 스크립트 내부 체크가 재차 걸러줌.
- **Artifact**: `if: always()`로 실패해도 업로드 시도. xlsx 생성 전에 실패하면 "No files found" 경고만 발생 (upload-artifact v4 기본 `if-no-files-found: warn`) — 무해함.
- `timeout-minutes: 10`, `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` env는 Node 버전 경고 제거용.

### 4.8 의존성 (`requirements.txt`)

```
requests, pandas, openpyxl, python-dateutil, urllib3, exchange-calendars
```

- **버전 핀 없음** → 매 실행마다 최신 버전 설치. 장점: exchange-calendars의 최신 공휴일 자동 반영. 단점: 상류 breaking change에 노출 (§7.8).
- `urllib3`는 `disable_warnings` 호출용으로만 import (현재 `verify=False`를 쓰지 않으므로 사실상 잔재 코드 — 제거해도 무방하나 유지 비용 0).

---

## 5. 운영 절차 (Runbook)

### 5.1 최초 설정

1. Google 계정 2단계 인증 활성화 → [앱 비밀번호](https://myaccount.google.com/apppasswords) 발급 (16자리).
2. 레포 **Settings → Secrets and variables → Actions**에 등록:
   - `GMAIL_SENDER` = 발신 Gmail 주소
   - `GMAIL_APP_PW` = 앱 비밀번호 (공백 포함돼도 무방)
   - `MAIL_RECIPIENTS` = `a@x.com,b@y.com` (콤마 구분)
3. Actions 탭 → `KOFIA Corp Bond Spread` → `Run workflow`로 1회 수동 검증.

### 5.2 자주 하는 변경 — 어디를 고치면 되는가

| 하고 싶은 것 | 수정 위치 | 방법 |
|---|---|---|
| 수신자 추가/삭제 | Secret `MAIL_RECIPIENTS` | 전체 목록을 새로 입력해 Update (기존 값 조회 불가) |
| 조회 기간 변경 | `kofia.yml` → `MONTHS: "3"` | 1/3/6/12 중 선택 |
| 채권 종류 변경 | `kofia.yml` → `BOND_GB: "7"` | KOFIA BIS 화면의 bondGbCode 값 확인 후 변경 |
| 실행 시각 변경 | `kofia.yml` → cron | **KST−9h를 UTC로 환산**, 자정 넘어가면 요일도 −1 시프트 |
| 메일 제목/본문 변경 | `kofia_spread.py:121-127` | 문자열 수정 |
| 엑셀 시트명/파일명 변경 | `kofia_spread.py:106-108` | 문자열 수정 |

### 5.3 로컬 테스트 방법

```bash
pip install -r requirements.txt
export SENDER_EMAIL="me@gmail.com" SENDER_PW="xxxxxxxxxxxxxxxx" RECIPIENTS="me@gmail.com"
export MONTHS=3 BOND_GB=7
python kofia_spread.py
# 성공 시: output/kofia_corp_spread_YYYYMMDD.xlsx 생성 + 메일 수신
```

- 비영업일에 테스트하면 즉시 `비영업일 - 종료`로 끝남. 강제 테스트하려면 `kofia_spread.py:31-33`의 체크를 **일시적으로** 주석 처리 (커밋 금지).
- 메일 없이 수집만 테스트: 발송 블록(`kofia_spread.py:111` 이후)을 주석 처리하거나, 수집 성공 로그(`등급: [...] / N행`, `저장: ...`)까지만 확인.

---

## 6. 변경 이력 (버그 이력 포함 — 재발 방지용)

| 버전 | 내용 |
|---|---|
| v1.0 | 초기 버전. Zoho → Gmail SMTP 전환, GitHub Actions 자동화 |
| v1.1 | **버그 수정**: 비영업일 체크가 `pass`로 되어 있어 휴일에도 진행되던 문제 → `sys.exit(0)`. cron KST 08:30 적용 |
| v1.2 | 영업일 체크를 워크플로우 Job으로 분리(skip 여부 사전 결정), cron KST 06:30(현재 06:23) 적용 |
| `7463172` | **버그 수정 (월요일 메일 미발송)**: 워크플로우 체크가 `previous_session(today) == 어제` 방식이어서, 월요일엔 직전 세션이 금요일이라 항상 false → Job 2가 매주 월요일 skip됨. `is_session(today)` 판정으로 교체하여 스크립트 로직과 통일 |

**교훈**: 영업일 판정 로직이 워크플로우와 스크립트 두 곳에 존재하므로, 둘 중 하나만 고치면 요일 의존적인 미묘한 버그가 생긴다. 반드시 동일 로직 유지.

---

## 7. 발생 가능한 오류 전체 카탈로그 & 해결 방법

> AI 트러블슈팅 절차: ① Actions 실행 로그에서 아래 **증상 문자열**을 찾는다 → ② 해당 항목의 진단 명령을 수행한다 → ③ 조치를 적용한다.

### 7.1 [빈도 높음] 특정 요일/특정 날에만 메일이 안 옴

- **증상**: Actions 이력에서 Job 2(`run`)가 `skipped`. 실패는 아님.
- **원인 후보**:
  1. 워크플로우 영업일 체크와 스크립트 체크의 로직 불일치 (과거 월요일 버그의 패턴).
  2. `exchange_calendars`가 해당일을 휴일로 잘못 알고 있음 (§7.4).
- **진단**: Job 1 로그의 `KST today: ..., is_open: ...` 출력 확인. `is_open: false`인데 실제 영업일이면 캘린더 문제.
- **조치**: 캘린더 문제면 §7.4. 로직 불일치면 양쪽을 `xkrx.is_session(today)` 기준으로 통일.

### 7.2 `수집 0행 — 응답 비어있음 (해외 IP 차단 가능성)`

- **증상**: 위 문자열로 exit 1. 메일 미발송.
- **원인 후보** (가능성 순):
  1. KOFIA 서버 점검 / 일시 장애 (아침 시간대 점검 잦음)
  2. KOFIA의 해외 IP 차단 (GitHub 러너는 주로 미국 IP)
  3. KOFIA API 스펙 변경 (DTO 이름, 파라미터 변경 → 정상 응답이지만 파싱 결과 0행)
- **진단**:
  1. 수동 재실행(`Run workflow`) — 일시 장애면 해결.
  2. 국내 PC에서 §5.3 로컬 테스트 — 국내에서 되고 러너에서 안 되면 IP 차단 확정.
  3. `fetch()` 직후 `print(r.text[:2000])`를 임시 추가해 실제 응답 확인 — 에러 XML/HTML이면 스펙 변경 또는 차단 페이지.
- **조치**:
  - 일시 장애: 재실행으로 끝.
  - IP 차단: **self-hosted runner**(국내 PC/서버)로 전환 — `kofia.yml`의 `runs-on: ubuntu-latest`를 `runs-on: self-hosted`로 변경 + 러너 등록. 또는 국내 리전 프록시 경유.
  - 스펙 변경: 브라우저 개발자도구(F12 → Network)로 KOFIA BIS 화면(회사채 신용스프레드 메뉴)의 실제 XHR 요청을 캡처해 `fetch()`의 바디/헤더/`pfmSvcName`을 새 스펙에 맞게 갱신. 응답 태그가 바뀌었으면 `parse_ratings`/`parse_body`의 태그명(`BISSprdIdxListDTO` 등)도 수정.

### 7.3 `xml.etree.ElementTree.ParseError`

- **증상**: traceback으로 실패. `ET.fromstring(r.text)`에서 발생.
- **원인**: KOFIA가 XML 대신 HTML(차단/점검/에러 페이지)을 반환.
- **진단/조치**: §7.2와 동일 절차. 본질적으로 같은 문제의 다른 표면.

### 7.4 [구조적 리스크] 임시공휴일·대체공휴일 미반영

- **증상 A**: 임시공휴일(예: 선거일 급지정)에 실행됨 → KOFIA에 그날 데이터가 없어 전일 데이터가 오거나 0행 실패.
- **증상 B**: 실제 영업일인데 캘린더가 휴일로 판정 → 조용히 skip, 메일 안 옴.
- **원인**: `exchange_calendars` 패키지의 XKRX 캘린더는 라이브러리 릴리스에 의존. 한국 정부의 임시공휴일 지정이 라이브러리에 반영되기까지 시차 존재.
- **진단**:
  ```bash
  pip install -U exchange_calendars
  python -c "import exchange_calendars as x; print(x.get_calendar('XKRX').is_session('2026-XX-XX'))"
  ```
- **조치**:
  - 의존성이 버전 미고정이므로 보통 **라이브러리 업데이트 후 자연 해결** (매 실행마다 최신 설치).
  - 라이브러리 반영 전 긴급 대응: 임시공휴일이면 그날 워크플로우를 수동으로 안 돌리면 되고(어차피 cron 1회), 반대 케이스(영업일인데 skip)면 `Run workflow` 수동 실행 — 수동 실행은 Job 1 체크를 우회하지만 **스크립트 내부 체크가 또 있으므로**, 캘린더가 틀린 상황에서는 스크립트도 exit 0으로 끝남. 이 경우 `kofia_spread.py:31-33`을 임시 주석 처리한 브랜치에서 실행하거나 라이브러리 반영을 기다릴 것.

### 7.5 `SMTPAuthenticationError` — `인증 실패: Gmail 앱 비밀번호 16자리 확인`

- **원인 후보**:
  1. 일반 Gmail 비밀번호를 넣음 (앱 비밀번호 아님)
  2. 앱 비밀번호 오타/폐기(revoke)됨
  3. Google 계정 2단계 인증이 꺼져 앱 비밀번호가 무효화됨
  4. Google이 보안 이슈로 앱 비밀번호를 자동 폐기 (비밀번호 변경 시 전체 폐기됨)
- **조치**: 2단계 인증 확인 → 앱 비밀번호 **재발급** → Secret `GMAIL_APP_PW` Update. 공백은 코드가 제거하므로 그대로 붙여넣어도 됨.

### 7.6 `KeyError: 'SENDER_EMAIL'` (또는 `SENDER_PW`, `RECIPIENTS`)

- **원인**: Secret 미등록, Secret 이름 오타, 또는 `kofia.yml`의 `env:` 매핑 누락. **Fork한 레포나 Fork에서 온 PR에서는 Secrets가 주입되지 않는 것이 정상 동작**.
- **조치**: Secret 이름 3종(`GMAIL_SENDER`, `GMAIL_APP_PW`, `MAIL_RECIPIENTS`)과 `kofia.yml:55-57`의 매핑이 일치하는지 확인.

### 7.7 스케줄이 아예 안 돎 (실행 이력 자체가 없음)

- **원인 후보**:
  1. **60일 무커밋 → GitHub이 스케줄 자동 비활성화** (가장 흔함)
  2. cron 요일값 실수 (`1-5`로 쓰면 KST 화~토 실행)
  3. 워크플로우 파일이 default 브랜치(main)에 없음 — schedule 트리거는 **main의 파일만** 읽음
  4. GitHub Actions 자체 장애
- **조치**:
  1. Actions 탭에서 "This workflow was disabled" 배너 확인 → Enable + 아무 커밋 하나 push. 예방책: 60일 내 주기적 커밋.
  2. cron 검증: KST 시각 −9h → UTC. 자정을 역으로 넘으면 요일 −1. 현재 값 `"23 21 * * 0-4"` = KST 월~금 06:23이 정답 기준.
  3. 브랜치에서만 수정했다면 main에 머지.

### 7.8 어느 날 갑자기 traceback (코드 변경 없음)

- **원인**: 의존성 버전 미고정 → pandas/exchange-calendars 등의 breaking change 가능성.
- **진단**: 실패 로그의 traceback에서 라이브러리 확인. 직전 성공 실행의 "Install deps" 로그와 버전 비교.
- **조치 (단기)**: `requirements.txt`에 문제 패키지만 직전 정상 버전으로 핀 (예: `pandas==2.2.3`).
- **조치 (장기)**: 전체 버전 핀 + 주기적 수동 업데이트. 단, **exchange-calendars를 핀하면 신규 공휴일 반영이 멈추므로** 이 패키지만은 미고정 유지 또는 최소버전(`>=`) 지정을 권장.

### 7.9 메일은 발송됐는데 수신함에 없음

- **원인**: 스팸함 분류 / Gmail 발송 한도(일 ~500통, 수신자 수 기준) / 수신자 주소 오타.
- **진단**: 로그에 `메일 발송 완료`가 있으면 SMTP는 성공한 것. 수신자별 스팸함 확인 → 발신 Gmail의 "보낸편지함" 확인.
- **조치**: 스팸 해제 + 발신자 주소록 등록. 수신자 목록이 크면 한도 고려.

### 7.10 엑셀 데이터가 이상함 (컬럼 밀림, 등급-값 불일치)

- **원인**: §4.3의 핵심 가정 붕괴 — KOFIA가 등급 컬럼 구성/순서를 변경.
- **진단**: KOFIA BIS 웹 화면의 표와 엑셀을 직접 대조. `parse_ratings()` 결과(로그의 `등급: [...]`)와 웹 화면 컬럼 순서 비교.
- **조치**: 웹 XHR 응답을 캡처해 `val{N}` ↔ 등급명 대응을 재확인하고 `parse_body()`의 인덱스 매핑 수정.

### 7.11 `requests.exceptions.Timeout` / `ConnectionError`

- **원인**: KOFIA 응답 지연(타임아웃: 워밍업 15s, 본 요청 30s), 네트워크 일시 장애.
- **조치**: 수동 재실행. 반복되면 timeout 상향(`kofia_spread.py:50,70`) 또는 재시도 로직 추가 (`requests.adapters.HTTPAdapter(max_retries=3)`).

### 7.12 Artifact에 "No files found matching: output/*.xlsx" 경고

- **원인**: xlsx 생성 전에 스크립트가 실패/스킵됨. upload-artifact는 `warn`만 하고 통과.
- **조치**: 이것 자체는 무해. 근본 원인(위 항목들 중 하나)을 해결하면 사라짐.

### 7.13 수동 실행했는데 아무 일도 안 일어남

- **원인**: 오늘이 비영업일 → 워크플로우 체크는 `workflow_dispatch`로 우회되지만 **스크립트 내부 체크(§4.2)가 exit 0** 처리. 로그에 `비영업일 - 종료` 출력됨.
- **조치**: 정상 동작. 비영업일에 강제로 돌리고 싶으면 §5.3의 임시 주석 처리 방식 사용.

---

## 8. 알려진 제약 / 기술 부채

| # | 항목 | 영향 | 개선 아이디어 |
|---|---|---|---|
| 1 | GitHub cron 지연 (5~30분+) | 06:23 설정이나 실제 실행은 유동적 | 정시성 필요 시 self-hosted runner |
| 2 | 실패 시 재시도 없음 | 일시 장애도 그날 메일 누락 | 워크플로우에 retry step 또는 실패 시 재스케줄 |
| 3 | 실패 알림이 커밋 작성자 메일로만 감 | 수신자는 누락을 모름 | 실패 시 안내 메일 발송 step 추가 |
| 4 | 의존성 버전 미고정 | §7.8 리스크 | 선택적 버전 핀 |
| 5 | val{N} 위치 기반 매핑 | §7.10 리스크 | 응답에 등급 코드가 함께 오면 코드 기반 매핑으로 전환 |
| 6 | 데이터 누적 저장 없음 | 과거 파일은 Artifact 30일 후 소실 | 필요 시 레포/외부 스토리지에 append |
| 7 | 해외 IP 차단 가능성 | 전면 장애 시나리오 | self-hosted runner 전환 절차 §7.2 |

---

## 9. 수정 시 지켜야 할 불변조건 (Invariants)

AI가 코드를 수정할 때 **깨뜨리면 안 되는 것들**:

1. **영업일 판정 로직은 `kofia.yml` Job 1과 `kofia_spread.py` 양쪽에 존재하며 반드시 동일해야 한다.** 현재 기준: `xkrx.is_session(today)` (KST 오늘). 한쪽만 수정 금지.
2. **비영업일은 exit 0 (성공)** 이어야 한다. exit 1로 바꾸면 휴일마다 실패 알림이 발송된다.
3. **cron은 UTC**다. KST 기준 시각을 넣지 말 것. KST 평일 아침 = UTC `* * 0-4`(일~목).
4. Secrets 이름(`GMAIL_SENDER`, `GMAIL_APP_PW`, `MAIL_RECIPIENTS`)을 바꾸면 레포 Settings의 Secret도 함께 바꿔야 한다 — 코드만 바꾸면 KeyError.
5. KOFIA 요청의 `remainDayCnt`에는 이름과 달리 **개월 수**가 들어간다. "버그처럼 보여도" KOFIA 웹 UI와 동일한 스펙이므로 임의로 일수로 바꾸지 말 것.
6. 요청 헤더(특히 `Referer`, `Origin`, `X-Requested-With`, 브라우저형 UA)와 사전 GET 워밍업은 KOFIA 접근에 필요한 요소로 취급하고 제거하지 말 것.
7. 출력 파일명 패턴 `kofia_corp_spread_{YYYYMMDD}.xlsx`과 Artifact 경로 `output/*.xlsx`는 연동되어 있다 — 한쪽 변경 시 `kofia.yml:65`도 수정.
8. 스케줄 트리거는 **main 브랜치의 워크플로우 파일**만 읽는다. 스케줄/로직 변경은 main 머지까지 완료해야 반영된다.

---

## 10. AI 유지보수 빠른 참조 (Quick Reference)

```
증상으로 진입:
  "메일이 안 왔어요"        → §7.1(스킵?) → §7.7(스케줄?) → §7.9(스팸?) → Actions 로그 확인
  "Actions가 빨간불"        → 로그의 에러 문자열로 §7.2/7.3/7.5/7.6/7.8/7.11 매칭
  "데이터가 이상해요"       → §7.10
  "휴일인데 실행됐어요"     → §7.4 증상 A
  "평일인데 skip됐어요"     → §7.1 / §7.4 증상 B

수정으로 진입:
  스케줄/조회조건/러너      → .github/workflows/kofia.yml
  수집/파싱/엑셀/메일 로직  → kofia_spread.py
  수신자/계정               → GitHub Secrets (코드 수정 불필요)
  의존성                    → requirements.txt

검증:
  로컬: §5.3  /  원격: Actions 탭 Run workflow (영업일에)
  성공 판정 로그: "기준 영업일: YYYYMMDD" → "등급: [...] / N행" → "저장: ..." → "메일 발송 완료"
```
