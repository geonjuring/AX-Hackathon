# AX-Hackathon · SLP 통합 리포트

2026 전남광주 기업 AX 혁신챌린지 팀 프로젝트입니다. 생산·품질·설비·전력 기록을 연결하여 **경영 리포트 / LOT 이상 분석 / 설비 이상 분석**을 하나의 Streamlit 앱에서 제공합니다.

숫자는 계산 엔진이 산출하고 AI는 설명을 보조합니다. 관측 이상과 원인은 구분하며, 기준·기록이 부족하면 판정을 보류합니다. 예측은 참고 추세이며 모의 알림은 실제 메시지를 보내지 않습니다.

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

각 스크립트가 읽는 파일명·컬럼은 `prep.py`, `prep_equip.py`, `management_snapshot/production_report.py`, `management_snapshot/billing_allocation.py`에 정의되어 있습니다. 원본 데이터는 GitHub로 올리지 마세요.

```bash
# 다른 위치를 쓸 때만 설정합니다. 생략하면 저장소의 data/를 사용합니다.
export SLP_DATA="/absolute/path/to/authorized/deidentified/data"
export SLP_DB="$PWD/slp.duckdb"

# 기존 DB가 없을 때 순서대로 실행합니다.
python prep.py
python prep_equip.py
```

주의: `prep.py`는 지정된 기존 DB를 삭제하고 재생성합니다. 운영 중인 DB 대신 별도의 새 경로에서 준비하세요. 피더 CSV가 커서 데이터 준비에 시간과 여유 디스크 공간이 필요합니다.

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

키가 없으면 규칙 기반 설명으로 동작합니다. 실제 키·호출 권한 및 첫 질문·후속 질문의 완료 응답은 운영자가 별도 검증해야 합니다. `check_agentstream.py`는 연결 확인용이며, `verify_agentstream.py`와 `check_agentstream.py --smoke`는 실제 모델 호출과 토큰 사용이 발생합니다.

AIStream은 기본 배포 서비스에 연결하며 적용 가능한 분석 범위에서 집계·운전 기록을 전송합니다. `AISTREAM_BASE_URL`, `AISTREAM_TIMEOUT_SECONDS`로 변경할 수 있습니다. 외부 API 장애 시 분석 보류·오류를 표시하며 미응답을 정상으로 판단하지 않습니다. 데이터 전송이 허용된 환경에서 사용하세요.

## 검증

다음 두 묶음은 합성 데이터와 대역 API로 검증하며 기업 데이터와 실제 API 키가 필요하지 않습니다.

```bash
python -m unittest discover -s . -p 'test_*.py'
PYTHONPATH="$PWD/management_snapshot" python -m unittest discover -s management_snapshot/tests -p 'test_*.py'
```

업로드 준비 시 분석·API·재생·리포트 테스트 **35개**, 경영 리포트 테스트 **36개**, 총 **71개**가 통과했습니다. 외부 API의 실제 응답과 다른 기기의 배포 접속은 별도 검증 항목입니다. 현재 환경에서 NumPy 시간 단위 관련 DeprecationWarning이 발생하며 테스트 실패는 아닙니다.

## 코드 구성

| 경로 | 역할 |
|---|---|
| `unified_app.py`, `slp_navigation.py` | 세 메뉴 통합 진입점 |
| `management_snapshot/` | 팀 경영 리포트 코드와 테스트 |
| `lot_analysis.py`, `equip_analysis.py` | LOT·설비 계산 엔진 |
| `prep.py`, `prep_equip.py` | CSV에서 분석 DB 준비 |
| `forecast.py`, `replay.py`, `data_quality.py` | 참고 예측·과거 재생·품질 점검 |
| `agentstream_client.py`, `aistream_client.py` | 외부 AI 서비스 연결 |
| `report_export.py`, `report_sections.py` | 다운로드 및 리포트 구성 |
| `docs/ANALYSIS_GUIDE.md` | 세부 분석 기준·적용 범위·한계 |
| `docs/SUBMISSION_CHECK.md` | 첨부 대회 체크리스트에 따른 점검 결과 |

경영 리포트의 `configure_schedule`은 원래 팀 서버의 경로와 UTC cron을 전제로 하는 운영용 함수입니다. 일반 실행에 필요하지 않으며 다른 서버에서 예약 실행하려면 운영자가 경로·환경변수·접근 권한을 검토해야 합니다. 저장소 업로드 작업은 cron을 등록하거나 기존 서버를 재시작하지 않습니다.

대회 제출 마감은 첨부 안내 기준 **2026-11-08 11:50 (한국시간)**입니다. 배포 URL·발표자료·온라인 폼·USB 제출은 이 코드 업로드와 별도입니다.
