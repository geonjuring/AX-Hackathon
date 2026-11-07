"""Operator-only synthetic first/follow-up check, using a server environment key."""
import json
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from agentstream_client import Client, Conversation, AgentStreamError


def main():
    report={'status':'incomplete','synthetic_only':True,'checked_at':datetime.now(timezone.utc).isoformat()}
    try:
        client=Client()
        if not client.config.key:
            print('AGENTSTREAM_API_KEY를 서버 셸 환경변수로 설정하세요. 키를 채팅이나 파일에 넣지 마세요.')
            return 2
        owner='operator-'+str(uuid4());scope=client.config.signature()
        conversation=Conversation(owner,scope)
        first=client.ask(conversation,owner,scope,
            '실제 생산 데이터가 아닌 연동 검증용 가상 사례입니다. 배럴 설정 200℃, 실측 210℃와 211℃에서 화면 강조와 판정 의미를 각각 설명하세요. 출처는 문서명과 근거 요약만 쓰고 종합 주의사항은 마지막에 제시하세요.')
        print('첫 질문 turn.completed 확인\n'+first.text)
        follow=client.ask(conversation,owner,scope,
            '앞선 가상 사례에서 211℃라는 관측만으로 불량 확정 또는 원인 확정이 가능한지 설명하고 필요한 현장 기준을 알려주세요.')
        print('동일 세션 후속 질문 turn.completed 확인\n'+follow.text)
        report.update(status='passed',completed_turns=2,nonempty_answers=bool(first.text.strip() and follow.text.strip()))
        Path(__file__).with_name('agentstream-verification.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print('API 완료 검증 통과. 답변의 문서 근거·판정 보류·종합 주의사항은 운영자가 함께 확인하세요.')
        return 0
    except AgentStreamError as exc:
        print('연결 미완료:',str(exc),'단계:',exc.stage,'HTTP:',exc.status or '—')
        return 2


if __name__=='__main__':raise SystemExit(main())
