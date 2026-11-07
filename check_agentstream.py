"""Explicit connection checks; never prints API keys or session identifiers."""
import argparse
from agentstream_client import Client,Conversation,AgentStreamError


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--smoke',action='store_true',help='연결 상태 확인 후 가상 온도 사례로 실제 모델 응답까지 검사')
    args=parser.parse_args()
    try:
        client=Client()
        if not args.smoke:
            state=client.health()
            print('health 상태:',state['status'],'확인시각:',state['checked_at'])
            print('health만으로 실제 답변 완료를 보장하지 않습니다.')
            return 0 if state['status']=='healthy' else 1
        scope=client.config.signature()
        text='연동 검증용 가상 시나리오입니다. 배럴 설정 중앙값 200℃, 실측 중앙값 210℃와 211℃에서 화면 강조와 판정 의미를 각각 설명해주세요. 실제 생산 데이터가 아닙니다. 근거는 문서명과 요약만 표시하세요.'
        response=client.ask(Conversation('server-smoke',scope),'server-smoke',scope,text)
        print('실제 AgentStream turn.completed 확인')
        print(response.text)
        return 0
    except AgentStreamError as exc:
        print('연결 미완료:',str(exc),'단계:',exc.stage,'HTTP:',exc.status or '—')
        return 2


if __name__=='__main__':raise SystemExit(main())
