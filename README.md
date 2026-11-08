# AX-Hackathon · SLP 통합 리포트

2026 전남광주 기업 AX 혁신챌린지 팀 프로젝트입니다. 생산·품질·설비·전력 기록을 연결하여 **경영 리포트 / LOT 이상 분석 / 설비 이상 분석**을 하나의 Streamlit 앱에서 제공합니다.

숫자는 계산 엔진이 산출하고 AI는 설명을 보조합니다. 관측 이상과 원인은 구분하며, 기준·기록이 부족하면 판정을 보류합니다. 예측은 참고 추세이며 모의 알림은 실제 메시지를 보내지 않습니다.

공용 시연 주소: **https://devopen-gpu.jntp-ax.or.kr/i/4TidQOAXSih_aFpf/**

AgentStream 연결·검증은 [연동 안내](docs/AGENTSTREAM.md), 서버 실행·재시작은 [배포 안내](docs/DEPLOYMENT.md)를 참고하세요.

## 주요 기능

- 경영 리포트: 일간·주간·월간 생산, LOT, 근무조, 전력 및 청구기준 집계
- LOT·설비 분석: 품질·운전 조건 비교, 전체 호기 조회, 데이터 품질 요약
- 과거 사례 재생: 기준 생산일 마감 이후 기록을 제외한 분석과 선택적 이후 실측 비교
- HTML·JSON·CSV 리포트 다운로드, 참고 추세 예측, 세션별 모의 알림
- AIStream 운전 패턴 분석 및 선택적인 AgentStream 설명 연결

## 실행 환경과 설치

검증 환경은 Python 3.12입니다. Linux/macOS에서는 다음과 같이 설치합니다. Windows에서도 가상환경 활성화 뒤 동일한 Python 명령을 사용할 수 있습니다.

```bash
git clone https://github.com/geonjuring/AX-Hackathon.git
cd AX-Hackathon
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

`requirements.txt`는 앱의 직접 의존성을, `requirements.lock.txt`는 팀 서버 검증 환경의 전체 패키지 버전을 기록합니다. 외부 환경의 패키지 설치는 별도 확인이 필요합니다.

## 데이터 준비

**이 공개 저장소에는 기업 실데이터·직원 명부·DuckDB·캐시·다운로드 리포트가 포함되지 않습니다.** 코드만 내려받은 상태에서는 실제 리포트를 생성할 수 없습니다. 권한 있는 팀원은 별도로 전달받은 정제 데이터로 실행하세요. 공개 시연에는 더미 또는 비식별 데이터를 사용해야 하며, 단순 컬럼 삭제만으로 비식별성을 보장하지 않습니다.

데이터 루트에는 다음 폴더가 필요합니다.

```text
data/
  01_분석용/    # 생산계획·실적, 품질, 운전기록, 생산일보, 전력, 청구 자료
  02_기준정보/  # 코드 및 센서 기준정보
  03_에이전트용/ # 경영 리포트용 생산계획·실적
```

각 스크립트가 읽는 파일명·컬럼은 `scripts/prepare/prep.py`, `scripts/prepare/prep_equip.py`, `slp/management/production_report.py`, `slp/management/billing_allocation.py`에 정의되어 있습니다. 원본 데이터는 GitHub로 올리지 마세요.

```bash
# 다른 위치를 쓸 때만 설정합니다. 생략하면 저장소의 data/를 사용합니다.
export SLP_DATA="/absolute/path/to/authorized/deidentified/data"
export SLP_DB="$PWD/slp.duckdb"

# 기존 DB가 없을 때 순서대로 실행합니다.
python -m scripts.prepare.prep
python -m scripts.prepare.prep_equip
```

주의: `scripts/prepare/prep.py`는 지정된 기존 DB를 삭제하고 재생성합니다. 운영 중인 DB 대신 별도의 새 경로에서 준비하세요. 피더 CSV가 커서 데이터 준비에 시간과 여유 디스크 공간이 필요합니다.

이미 팀에서 준비한 DB가 있으면 준비 명령 대신 `SLP_DB`를 해당 파일로 지정합니다. 경영 리포트에는 DB 외에도 위 CSV가 필요합니다.

## 통합 앱 실행

```bash
bash run.sh
```

기본 접속 주소는 `http://localhost:8501`이며 왼쪽 메뉴에서 세 리포트를 전환합니다. Python으로 직접 실행할 수도 있습니다.

```bash
python -m streamlit run unified_app.py
```

`SLP_PYTHON`, `PORT`, `BIND_ADDRESS`, `BASE_PATH` 환경변수로 실행 환경을 바꿀 수 있습니다. 외부 접속이 필요하면 운영 환경에서 `BIND_ADDRESS=0.0.0.0`과 프록시·접근 권한을 설정하세요. 외부 공개 전에 데이터와 다운로드 내용도 확인해야 합니다. `app.py`는 LOT·설비 분석만 제공하는 별도 진입점입니다.

## 선택적 AI 연결

AgentStream API 키는 **서버 환경변수** `AGENTSTREAM_API_KEY`로만 설정합니다. 필요에 따라 `AGENTSTREAM_BASE_URL`, `AGENTSTREAM_CHATBOT_ID`, `AGENTSTREAM_WORKSPACE_ID`를 지정합니다. `.env.example`은 빈 예시이며 앱이 `.env`를 자동으로 읽지 않습니다. 실제 키·비밀번호·인증 쿠키를 코드나 README에 넣지 마세요.

키가 없으면 규칙 기반 설명으로 동작합니다. 팀 배포에서는 팀 챗봇의 공개·CHAT_INVOKE 설정, 실제 첫 질문·동일 세션 후속 질문 및 공용 웹의 생성 완료를 확인했습니다. 새 환경에서는 운영자가 별도로 검증해야 합니다. `scripts/checks/check_agentstream.py`는 연결 확인용이며, `scripts/checks/verify_agentstream.py`와 `scripts/checks/check_agentstream.py --smoke`는 실제 모델 호출과 토큰 사용이 발생합니다.

NDJSON의 `event`를 메시지 자료형인 `type`보다 우선해 처리합니다. 여러 계산표는 표 이름·행·항목을 보존한 설명 문맥으로 전달하여 단일 JSON 표 입력과 구분합니다. 값 0·음수·문자열 식별자·결측을 구분하며, 입력 한도를 넘으면 잘라 보내지 않고 범위 축소를 안내합니다. 생성 완료는 답변 정확성 검증 완료를 뜻하지 않습니다. 모델의 규격·예측·출처 표현은 계산표와 승인된 현장 기준에 대조해야 합니다.

AIStream은 기본 배포 서비스에 연결하며 적용 가능한 분석 범위에서 집계·운전 기록을 전송합니다. `AISTREAM_BASE_URL`, `AISTREAM_TIMEOUT_SECONDS`로 변경할 수 있습니다. 외부 API 장애 시 분석 보류·오류를 표시하며 미응답을 정상으로 판단하지 않습니다. 데이터 전송이 허용된 환경에서 사용하세요.

## 검증

다음 명령은 전체 자동 테스트를 실행합니다. 합성 데이터와 대역 API를 사용하며 기업 데이터와 실제 API 키가 필요하지 않습니다.

```bash
python -m unittest discover -s tests -t . -p 'test_*.py'
```

2026-11-08 최신 후보 소스를 팀 서버의 별도 폴더에서 Python 3.12.3으로 검증했습니다. 분석·API·재생·리포트 테스트 **37개**, 경영 리포트 테스트 **36개**, 기존 **73개**가 통과했습니다. 폴더 정리 후에는 경로·모듈 실행 회귀 테스트 **3개**를 추가해 총 **76개**가 통과했습니다. 운영 DB와 실제 API 키는 이 테스트에 사용하지 않았습니다. 실제 API와 공용 웹 검증 기록은 [연동 안내](docs/AGENTSTREAM.md)를 참고하세요. 신규 기기 설치·다른 기기의 시연 접속은 별도 확인 항목입니다. 기존 NumPy 시간 단위 관련 DeprecationWarning은 남아 있으며 테스트 실패는 아닙니다.

## 코드 구성

```text
unified_app.py       # 통합 실행점 (기존 명령 유지)
app.py               # LOT·설비 단독 실행점
slp/
  config.py          # 데이터·DB·런타임 경로
  ui/                # 내비게이션·화면·AI 패널·모의 알림
  analysis/          # LOT·설비·품질·예측·과거 재생
  ai/agentstream/    # 설명 생성 클라이언트와 문맥 구성
  ai/aistream/       # 운전 패턴 클라이언트와 분석
  management/        # 생산·전력·청구·근무조 경영 리포트
  reporting/         # HTML·JSON·CSV·ZIP 출력
  common/            # 숫자·표 표시
scripts/prepare/     # DB 준비 명령
scripts/checks/      # 수치 대조·운영 API 검증
tests/              # 모든 자동 테스트 (ai·analysis·management·common)
docs/                # 분석·연동·운영·검증 안내
```

각 폴더는 Python 패키지입니다. 저장소 루트에서 `python -m scripts.prepare.prep`처럼 모듈 명령을 사용하세요. 개별 스크립트 경로로 직접 실행하거나 `PYTHONPATH`를 임의 수정할 필요가 없습니다.

DB와 CSV 기본 위치는 이전과 같이 저장소 루트의 `slp.duckdb`, `data/`입니다. 코드 파일 위치와 분리되어 폴더 이동에 영향받지 않습니다. 캐시·생성 리포트·경영 조회 설정·API 검증 결과는 `runtime/`에 저장하며 Git에서 제외합니다. 다른 위치는 `SLP_RUNTIME` 환경변수로 지정합니다. 이전 경영 조회 설정을 유지하려면 기존 `report_settings.json`을 새 런타임 디렉터리로 별도 복사하세요.

경영 리포트 CLI는 `python -m slp.management.production_report --date latest`입니다. `configure_schedule`은 현재 Python·저장소·데이터·런타임 경로를 사용하며 UTC cron을 전제로 합니다. 운영자가 예약을 명시적으로 설정할 때만 실행합니다. 폴더 정리 작업으로 예약 작업이 자동 등록되지는 않습니다.

정리 전후 검증 범위와 되돌리기 절차는 [폴더 정리 검증](docs/ORGANIZATION.md)을 참고하세요.

대회 제출 마감은 첨부 안내 기준 **2026-11-08 11:50 (한국시간)**입니다. 배포 URL·발표자료·온라인 폼·USB 제출은 이 코드 업로드와 별도입니다.
