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

## 📈 ABS보증 수요 점검 확장 (v2.0)

매일 수집분을 `data/spread_history.csv`에 누적하고, **SGI 보증(AAA 부여) 시 발행사 금리 절감폭**을 지표화해 메일 본문에 표·차트로 보여줍니다.

### 지표 정의

| 지표 | 계산 | 의미 |
|---|---|---|
| 국고대비(bp) | (등급금리 − 국고채금리) × 100 | 시장 전반 신용위험 분위기 |
| **보증차익(bp)** | 등급 스프레드 − AAA 스프레드 | 우리 보증서의 경제적 가치 (수요 지표) |
| 순차익(bp) | 보증차익 − `SGI_PREMIUM_BP` | SGI 보증물이 순수 AAA보다 더 받는 금리 차감 |
| %ile | 최근 `PCTL_YEARS`년 분포 내 위치 | 높을수록 스프레드 넓음 = 보증 수요 국면 |

- 관심 등급: AA- / A+ / A / A- (취급 범위), 기준선 AAA, 경색 신호 BBB+
- 알림: A등급대 보증차익 3년 상위 20% 진입 · 1주 ±10bp 급변 · A-↔BBB+ 격차 1개월 +10bp 확대

### 결과물

- 메일 본문: 신호 목록 + 요약표 + 차트 2종(등급별 국고대비 스프레드 / 보증차익 + 보증료 밴드)
- 엑셀 시트: `회사채_신용스프레드`(기존 원자료) · `요약_3M` · `국고대비bp_3M` · `보증차익bp_3M`
- 이력: `data/spread_history.csv` (date, tenor, grade, value) — 워크플로우가 매 실행 후 커밋 (keepalive 효과도 겸함)

### 추가 환경변수 (`kofia.yml`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `REMAIN_DAY_CNT` | `MONTHS`와 동일 | KOFIA `remainDayCnt` 값. 콤마로 여러 개 (예: `3,12,36`) |
| `BACKFILL_MONTHS` | `0` | 수동 실행 입력값. 예: `60` → 5년치 12개월 단위 분할 조회 후 적재 |
| `CHART_MONTHS` | `24` | 차트 표시 기간 |
| `PCTL_YEARS` | `3` | 백분위 창 |
| `SGI_PREMIUM_BP` | `0` | SGI 보증 ABS 실제 발행금리 − AAA 민평 (실적 사례로 보정) |
| `FEE_BAND_BP` | (없음) | `"40,80"` 처럼 지정 시 보증차익 차트에 보증료 밴드 표시 |
| `VALUE_MODE` | `auto` | KOFIA 값이 금리(`yield`)인지 스프레드(`spread`)인지. auto는 자동 판정 |
| `DRY_RUN` | — | `1`이면 메일 대신 `output/mail_preview_*.eml` 저장 |

### 최초 1회: 과거 이력 적재

Actions → `KOFIA Corp Bond Spread` → Run workflow → `backfill_months`에 `60` 입력 (2022.10 레고랜드 구간 포함 권장).
Settings → Actions → General → Workflow permissions가 **Read and write**여야 이력 커밋이 됩니다 (keepalive와 동일 조건).

### ⚠️ 잔존만기(remainDayCnt) 검증 필요

기존 코드는 `remainDayCnt`에 조회기간 개월 수(`MONTHS`)를 넣어 왔습니다. 화면의 **잔존만기 선택값**(3개월물·1년물 등)에 해당한다면, 기존 `MONTHS`를 바꾸는 순간 조회기간이 아니라 **만기가 바뀌는** 문제가 있었습니다. v2.0은 두 값을 분리했으며 기본값은 기존 요청과 동일합니다.

검증 방법: KOFIA 화면에서 잔존만기만 바꿔 조회하며 개발자도구(Network) → `XMLSERVICES` 요청 본문의 `remainDayCnt` 값이 바뀌는지 확인. 바뀌면 `REMAIN_DAY_CNT: "3,12,36"`으로 확장하세요.

### 오프라인 점검

```bash
python tests/offline_run.py   # 합성 XML로 수집→누적→지표→차트→메일(.eml)까지 실행, 임시폴더에 결과
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
matplotlib
```

Python 3.11+ 권장.

---

## 📝 변경 이력

- v1.0 — 초기 버전 (Zoho → Gmail SMTP 전환, GitHub Actions 자동화)
- v1.1 — 영업일 체크 버그 수정 (`pass` → `sys.exit(0)`), cron KST 08:30 적용
- v1.2 - 영업일 체크를 workflow단에서 체크하여 skip여부 결정, cron KST 06:30 적용
- v2.0 — 이력 누적(data/spread_history.csv), 보증차익·백분위·알림, HTML 메일 차트, 백필, remainDayCnt/조회기간 분리
