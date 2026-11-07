# 통합 웹 실행과 운영

## 실행점과 데이터

공용 주소는 https://devopen-gpu.jntp-ax.or.kr/i/4TidQOAXSih_aFpf/ 입니다. 통합 실행점은 `unified_app.py`이며 `run.sh`가 이를 실행합니다. 경영 리포트는 `management_snapshot/`, LOT·설비 메뉴는 `slp_navigation.py`로 연결합니다. `app.py`는 LOT·설비만 제공하는 별도 실행점입니다.

Python 3.12 가상환경에 `requirements.txt`를 설치하고, 권한 있는 정제 CSV와 분석 DB를 별도로 준비합니다. 경영 리포트에는 DB 외에 CSV도 필요합니다. 저장소 기본값은 `data/`와 `slp.duckdb`이며 다른 위치는 `SLP_DATA`, `SLP_DB`로 지정합니다. `prep.py`는 DB를 재생성하므로 실행 중인 DB에 사용하지 않습니다.

```bash
export SLP_DATA="/absolute/path/to/authorized/deidentified/data"
export SLP_DB="/absolute/path/to/slp.duckdb"
export SLP_PYTHON="/absolute/path/to/venv/bin/python"
bash run.sh
```

기본 바인드는 `127.0.0.1:8501`입니다. 새 서버에서는 먼저 이 상태로 확인하고 프록시·접근 권한에 맞춰 외부 바인드를 설정합니다.

## AgentStream 키와 시작

`.env.example`은 설정 항목의 예시이며 앱은 `.env`를 자동으로 읽지 않습니다. 키는 실행 프로세스의 환경변수 또는 별도 비밀 관리 도구로 주입합니다. 다음은 Bash의 숨김 입력 예시입니다. 키를 명령 인수·파일·README·채팅에 넣지 않습니다.

```bash
read -r -s -p 'AgentStream API key: ' AGENTSTREAM_API_KEY
printf '\n'
export AGENTSTREAM_API_KEY
export AGENTSTREAM_TIMEOUT_SECONDS=120
# 다른 워크스페이스/챗봇을 사용할 때만 해당 ID를 지정합니다.
# export AGENTSTREAM_CHATBOT_ID="..."
# export AGENTSTREAM_WORKSPACE_ID="..."
python check_agentstream.py
# 실제 호출과 토큰 사용이 발생하는 검증입니다.
python verify_agentstream.py
bash run.sh
```

팀 배포에서는 키를 파일에 저장하지 않고 검증 프로세스와 공용 프로세스의 환경변수에 주입했습니다. **서버 재부팅이나 새 앱 프로세스 시작 시 키를 안전하게 다시 주입해야 합니다.** 브라우저 새로고침에는 재입력이 필요하지 않습니다. 기존 프로세스의 환경변수는 다른 셸에서 export해도 바뀌지 않습니다. OS 부팅 시 자동 실행과 영구 비밀 저장은 구성하지 않았습니다.

## 팀 프록시 설정

팀 공용 배포는 8501 포트와 다음 프록시 경로를 사용합니다. 다른 환경에서는 운영자가 실제 포트·경로를 지정합니다.

```bash
export PORT=8501
export BIND_ADDRESS=0.0.0.0
export BASE_PATH=i/4TidQOAXSih_aFpf
bash run.sh
```

위 명령을 기존 8501 서비스가 실행 중인 상태에서 중복 실행하지 않습니다. 이 저장소의 코드를 수정하거나 GitHub에 푸시하는 것만으로 서버가 자동 배포되지는 않습니다.

## 변경 반영과 복구

1. 배포할 커밋, 기존 통합 앱 프로세스·실행 폴더·포트를 확인합니다. 경영 리포트의 별도 원본 서비스와 DB는 대상에서 제외합니다.
2. 별도 검증 포트와 격리된 실행 폴더에서 테스트합니다. 새 환경의 데이터 경로·권한·AgentStream 키와 공개/CHAT_INVOKE를 확인합니다.
3. health 성공 후 실제 첫 질문·동일 세션 후속 답변의 완료를 확인합니다. health나 HTTP 200만으로 성공을 판단하지 않습니다.
4. 검증한 통합 앱 프로세스만 교체합니다. 기존 버전과 안전한 키 주입 수단을 복구에 사용할 수 있게 유지합니다. 모든 Python 프로세스를 일괄 종료하지 않습니다.
5. 공용 주소에서 경영·LOT·설비 메뉴, 실제 AI 응답, 실패 시 계산표 유지, HTML/ZIP의 응답 보존을 확인합니다. 문제가 생기면 기존 버전으로 복구합니다.

상태 확인 경로는 `/<BASE_PATH>/_stcore/health`입니다. 이것은 Streamlit 프로세스 상태이며 AgentStream 모델·도구 상태나 답변 품질을 보장하지 않습니다. 시연과 심사가 끝날 때까지 프로세스·프록시·사용량 한도를 운영자가 확인해야 합니다.
