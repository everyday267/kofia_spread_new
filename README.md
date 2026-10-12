# KOFIA 회사채 신용스프레드 자동 수집·발송

KOFIA 채권정보센터(BIS)에서 **회사채 신용등급별 스프레드**를 매 영업일 아침 자동으로 조회하여 Excel로 저장하고, 지정된 수신자에게 Gmail로 발송하는 GitHub Actions 기반 자동화 파이프라인입니다.

---

## 📌 개요

| 항목 | 내용 |
|---|---|
| 데이터 출처 | KOFIA 채권정보센터 (`www.kofiabond.or.kr`) |
| 조회 항목 | 회사채 신용등급별 스프레드 (국고채 대비) |
| 기준일 | 직전 KRX 영업일 |
| 조회 기간 | 기본 3개월 (환경변수로 변경 가능) |
| 실행 주기 | **평일 KST 08:30** (GitHub Actions cron) |
| 결과물 | `.xlsx` 파일 + Gmail 첨부 발송 + Actions Artifact 보관 (30일) |
| 실행 환경 | GitHub-hosted runner (`ubuntu-latest`, Python 3.11) |

---

## 🗂 파일 구성

```
.
├── kofia_spread.py                # 수집·파싱·엑셀 저장·메일 발송 본체
├── requirements.txt               # 파이썬 의존성
└── .github/
    └── workflows/
        └── kofia.yml              # GitHub Actions 스케줄/실행 정의
```

---

## ⚙️ 동작 흐름

1. **cron 트리거** — UTC 일~목 23:30 (= KST 월~금 08:30)
2. **영업일 체크** — `exchange_calendars.XKRX` 로 한국 주식시장 영업일 판정
   - 공휴일이면 `sys.exit(0)` 으로 조용히 종료 (성공 처리, 메일 미발송)
3. **KOFIA 호출** — ProFrame XML SOAP 엔드포인트(`/proframeWeb/XMLSERVICES/`) 에 POST
   - `BISCdtRnkSprdIdxSrchSO.selectCdtBndIdxList`
   - `wrkGbn=TBOND_SPRD`, `bondGbCode=7`(회사채)
4. **XML 파싱** — 등급명(`BISSprdIdxListDTO`) + 일자별 수치(`BISSprdIdxBodyListDTO`) 추출
5. **엑셀 저장** — `output/kofia_corp_spread_YYYYMMDD.xlsx`
6. **Gmail 발송** — `smtp.gmail.com:587` STARTTLS, 앱 비밀번호 인증
7. **Artifact 업로드** — 실행 결과 xlsx를 GitHub에 30일 보관

---

## 🔐 사전 설정

### 1. Gmail 앱 비밀번호 발급

1. Google 계정 → **보안 → 2단계 인증** 활성화
2. [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) 접속
3. 앱 이름 입력(예: `kofia-actions`) → 생성 → **16자리 비밀번호** 발급
4. 공백 4개를 제거한 16자리 문자열을 메모

> ⚠️ 일반 Gmail 로그인 비밀번호로는 SMTP 인증이 차단됩니다.

### 2. GitHub Secrets 등록

레포 **Settings → Secrets and variables → Actions → New repository secret**

| Name | 값 예시 | 비고 |
|---|---|---|
| `GMAIL_SENDER` | `yourid@gmail.com` | 보내는 Gmail 주소 |
| `GMAIL_APP_PW` | `abcdefghijklmnop` | 앱 비밀번호 16자리 (공백 제거) |
| `MAIL_RECIPIENTS` | `a@x.com,b@y.com` | 콤마 구분, 공백 없이 |

> 💡 Secrets 값은 등록 후 **다시 조회할 수 없습니다**. 수정은 `Update` 버튼으로 덮어쓰기만 가능.

---

## 🚀 사용 방법

### 수동 실행

레포 **Actions 탭 → `KOFIA Corp Bond Spread` → `Run workflow`** → `main` 브랜치 선택 → 초록 버튼 클릭.

### 자동 실행

`.github/workflows/kofia.yml` 의 cron 이 평일 08:30 KST 로 설정되어 있어 별도 조작 없이 자동 실행됩니다.

### 환경변수로 조회 조건 변경

`kofia.yml` 의 `env:` 블록에서 수정:

```yaml
env:
  MONTHS: "3"        # 1 / 3 / 6 / 12
  BOND_GB: "7"       # 7 = 회사채
```

### 수신인 변경

Secrets 의 `MAIL_RECIPIENTS` 를 `Update` 로 덮어쓰기. 전체 목록을 새로 입력하는 방식.

---

## 🛠 운영상 중요 사항

### 1. 스케줄 시간 정확도
GitHub Actions cron 은 **러너 부하에 따라 5~30분 지연 가능**합니다. 정시 보장이 필요하면 사내 서버 cron 또는 self-hosted runner 가 적합합니다.

### 2. cron 요일 변환 (UTC ↔ KST)
GitHub Actions cron 은 **UTC 기준**입니다. KST 평일 = UTC 일~목 이므로 요일값은 `0-4` 를 씁니다. `1-5` 로 잘못 적으면 KST 화~토 에 실행됩니다.

| KST 요일 | UTC 요일 | cron 요일값 |
|---|---|---|
| 월~금 | 일~목 | `0-4` |
| 매일 | 매일 | `*` |

### 3. 60일 무활동 시 스케줄 자동 비활성
레포에 60일간 커밋이 없으면 GitHub 가 스케줄을 자동 중지합니다. 가끔 사소한 커밋을 찍거나 Actions 탭에서 재활성화 필요.

### 4. 공휴일 처리
`kofia_spread.py` 상단의 영업일 체크 로직이 한국 주식시장 휴장일(신정·설·추석·광복절 등)을 자동으로 걸러냅니다. 휴장일엔 메일이 안 옵니다.

```python
if not xkrx.is_session(today):
    print(f"{today.date()} 비영업일(주말/공휴일) — 종료")
    sys.exit(0)
```

### 5. KOFIA 해외 IP 차단 리스크
GitHub-hosted runner 는 주로 미국 IP 입니다. KOFIA 가 향후 해외 IP 를 차단할 경우 응답이 비어 `수집 0행` 으로 실패합니다. 대안:
- **Self-hosted runner**: 국내 PC/서버에 runner 설치
- 한국 리전 프록시 경유

현재까지는 정상 동작 확인됨.

### 6. Gmail 첨부 한도
Gmail SMTP 첨부 한도는 **25MB** 입니다. 조회 기간을 12개월 이상으로 늘려도 통상 수십 KB 수준이라 문제 없음.

### 7. 실패 시 재시도 없음
한 번 실패하면 다음 스케줄까지 자동 재시도하지 않습니다. 실패 알림은 GitHub 가 기본적으로 커밋 작성자 이메일로 발송.

### 8. Secrets 보안
- workflow 로그에 Secrets 값은 `***` 로 자동 마스킹됨
- Fork된 PR 에서는 Secrets 미주입 → 보안상 안전
- 유출 의심 시 Google 계정에서 앱 비밀번호 즉시 Revoke 후 재발급

---

## 📊 결과물 형식

`kofia_corp_spread_YYYYMMDD.xlsx` (시트명: `회사채_신용스프레드`)

| 기준일 | 국고채금리 | AAA | AA+ | AA | AA- | A+ | ... |
|---|---|---|---|---|---|---|---|
| 20260528 | 3.123 | 3.456 | 3.512 | ... | | | |
| 20260527 | ... | ... | ... | ... | | | |

- **기준일 내림차순** 정렬 (최신이 맨 위)
- 수치 단위: %
- 등급 컬럼명은 KOFIA 응답의 `bondGbCodeNm` 그대로 사용

---

## 🧪 트러블슈팅

| 증상 | 원인 | 조치 |
|---|---|---|
| `Run workflow` 버튼 없음 | yml 의 `workflow_dispatch:` 누락 | yml 확인 후 main 브랜치 push |
| 인증 실패 (`SMTPAuthenticationError`) | 일반 비번 사용 / 앱 비밀번호 오타 | 2단계 인증 후 앱 비밀번호 재발급 |
| `수집 0행 — 응답 비어있음` | KOFIA 차단 / 해외 IP / 점검 | 시간 두고 재시도, 안되면 self-hosted runner |
| 스케줄 안 돔 | 60일 무활동 자동 중지 | Actions 탭에서 재활성화 + 커밋 |
| KST 화~토 에 실행됨 | cron 요일 `1-5` 로 잘못 입력 | `0-4` 로 수정 |
| 메일 안 옴 | 스팸함 / Secrets 오타 | 스팸함 확인, Secrets 재등록 |

---

## 📈 스프레드 이력 · ABS보증 차익 대시보드 (v2.0)

메일은 v1.2와 동일하게 발송하고, 그와 별도로 **이력을 누적해 HTML 대시보드를 저장소에 커밋**합니다.

| 결과물 | 경로 | 비고 |
|---|---|---|
| 이력 원자료 | `data/spread_history.csv` | long 형식 `date, tenor, grade, value` (국고채=금리 %, 등급=국고 대비 스프레드 %p) |
| 대시보드 | `docs/index.html` | 외부 라이브러리 없는 단일 HTML. 내려받아 열거나 GitHub Pages로 열람 |

- 실행 순서: 메일용 수집·엑셀 저장 → 이력/대시보드 갱신 → 메일 발송. 이력/대시보드 단계가 실패해도 **메일은 그대로 발송**
- 워크플로우가 실행 후 `data/`, `docs/` 변경분을 main에 커밋 (keepalive 효과도 겸함)
- GitHub Pages: Settings → Pages → Branch `main` / 폴더 `/docs` → `https://everyday267.github.io/kofia_spread_new/`

### 대시보드 구성

- 잔존만기 · 표시기간(6M/1Y/3Y/5Y/전체) 선택
- 보증료 밴드 · SGI보증물 프리미엄 입력칸 (브라우저에 기억)
- AA- / A+ / A / A- **보증차익** 타일: 최근값, 1개월 변동, 3년 %ile, 보증료 대비 순차익
- 신호: 보증차익 3년 상위 20% · 1주 ±10bp 급변 · A-↔BBB+ 격차 1개월 +10bp 확대
- 차트 2종(마우스 오버 시 일자별 값): 보증차익 + 보증료 밴드 / 국고대비 스프레드(AAA~BBB+)
- 등급별 요약표, 최근 60영업일 원자료 표

| 지표 | 계산 |
|---|---|
| 국고대비(bp) | KOFIA 등급 값(%p) × 100 |
| 보증차익(bp) | 해당 등급 스프레드 − AAA 스프레드 (동일 잔존만기) |
| 순차익(bp) | 보증차익 − SGI보증물 프리미엄 |
| %ile | 최근 3년 분포 내 위치 (높을수록 스프레드 넓음) |

### KOFIA 요청 코드 (2026-10-12 화면 컴포넌트에서 확인)

| 화면 항목 | 요청 필드 | 값 |
|---|---|---|
| 스프레드 / 수익률 | `wrkGbn` | `TBOND_SPRD`(국고 대비 스프레드) / `BOND_ROP`(수익률) |
| 채권종류 | `bondGbCode` | 특수채 `3` · 은행채 `5` · 기타금융채 `6` · **회사채 `7`** |
| 잔존만기 (화면 라벨은 '조회기간') | `remainDayCnt` | 개월 수: `3` `6` `9` `12` `18` `24` `30` `36` `60` |
| 조회일 from~to | `standardDt` ~ `uStandardDt` | `YYYYMMDD` |

- 응답의 기준일(`standardDt`)은 `YYYY-MM-DD` 형식 → 이력에서는 `YYYYMMDD`로 정규화
- `TBOND_SPRD` 응답: `val1` = 국고채 금리(%), `val2~` = 등급별 스프레드(%p). 회사채는 AAA~BBB- 10개 등급
- 수익률 = 국고채 금리 + 스프레드로 계산 가능 (`BOND_ROP` 응답과 0.01%p 이내로 일치 확인)
- 5년치 단건 조회도 응답함(약 9초). 백필은 12개월 단위로 분할 조회
- v1.2는 `remainDayCnt`에 `MONTHS`를 넣었지만 값이 3이라 3개월물이 맞게 조회되고 있었음. v2.0에서 분리

| 변수 | 기본값 | 설명 |
|---|---|---|
| `REMAIN_DAY_CNT` | `3` | 메일용 잔존만기 (3 = 국고 3개월물) |
| `HISTORY_TENORS` | `3,12,36` (workflow) | 대시보드에 쌓을 잔존만기 목록 |
| `BACKFILL_MONTHS` | `0` | Run workflow 입력값. 예: `60` → 5년치 적재 |

### 최초 1회

1. Settings → Actions → General → Workflow permissions = **Read and write**
2. Actions → `KOFIA Corp Bond Spread` → Run workflow → `backfill_months` = `60` (2022.10 경색 구간 포함)
3. (선택) Settings → Pages → `main` / `/docs`

### 오프라인 점검

```bash
python tests/test_real_fixture.py              # 실제 응답 구조(fixtures)로 파서·이력·대시보드 점검
python tests/offline_run.py                    # 합성 XML로 수집→메일(.eml)→이력→대시보드까지 실행 (임시 폴더)
BACKFILL_MONTHS=60 python tests/offline_run.py # 백필 경로
python spread_dashboard.py                     # data/spread_history.csv만으로 docs/index.html 재생성
```

---

## 📜 의존성

```
requests
pandas
openpyxl
python-dateutil
urllib3
exchange-calendars
```

Python 3.11+ 권장.

---

## 📝 변경 이력

- v1.0 — 초기 버전 (Zoho → Gmail SMTP 전환, GitHub Actions 자동화)
- v1.1 — 영업일 체크 버그 수정 (`pass` → `sys.exit(0)`), cron KST 08:30 적용
- v1.2 - 영업일 체크를 workflow단에서 체크하여 skip여부 결정, cron KST 06:30 적용
- v2.0 — 메일은 v1.2 유지. 이력 누적(data/spread_history.csv) + HTML 대시보드(docs/index.html) 커밋, 백필, remainDayCnt(잔존만기)/조회기간 분리
