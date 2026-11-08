"""Explicit per-visitor, per-report AI generation. No secret or session IDs in UI."""
from uuid import uuid4
import streamlit as st
from slp.ai.agentstream.client import Client, Config, Conversation, AgentStreamError
from slp.ai.agentstream.context import build_payload, build_message, payload_id, rule_summary
import slp.common.table_display as TD


def render(res,kind,forecast=None):
    outcome={'방식':'규칙 기반','답변':rule_summary(res,kind),'완료':False}
    with st.expander('AgentStream 설명 · 질문',expanded=True):
        try:
            payload=build_payload(res,kind,forecast)
            cfg=Config.from_env()
        except AgentStreamError as exc:
            st.warning(str(exc));st.markdown(TD.text(outcome['답변']))
            return outcome
        scope=cfg.signature()+':'+payload_id(payload)
        owner=st.session_state.setdefault('agentstream_visitor',str(uuid4()))
        contexts=st.session_state.setdefault('agentstream_contexts',{})
        if scope not in contexts:
            if len(contexts)>=10: contexts.pop(next(iter(contexts)))
            contexts[scope]={'conversation':Conversation(owner,scope),'turns':[],'health':None}
        state=contexts[scope]
        if not cfg.key:
            st.caption('연결 코드 준비 완료 · API 키 미설정 · 외부 전송 없음')
        else:
            st.caption('사용자가 생성·질문 버튼을 누를 때 선택 범위의 집계와 질문을 서버에서 전송합니다. 입력과 응답은 AgentStream의 대화 보관 정책에 따라 저장될 수 있습니다.')
        a,b=st.columns(2)
        if a.button('AgentStream 연결 상태 확인',disabled=not cfg.key,key=scope+'health'):
            try:
                state['health']=Client(cfg).health()
                st.info('연결 상태: '+state['health']['status']+' · health 응답만으로 실제 답변 완료를 보장하지 않습니다.')
            except AgentStreamError as exc:
                st.warning(str(exc))
        if b.button('새 AI 대화',key=scope+'reset'):
            state['conversation']=Conversation(owner,scope);state['turns']=[]
            st.rerun()
        question=st.text_input('분석 결과에 대한 질문',key=scope+'question',placeholder='예: 다음 생산 전에 먼저 확인할 항목은?')
        left,right=st.columns(2)
        generate=left.button('AgentStream 리포트 생성',disabled=not cfg.key,key=scope+'generate')
        follow=right.button('질문 보내기',disabled=not cfg.key or not question.strip(),key=scope+'ask')
        if generate or follow:
            if generate:
                state['conversation']=Conversation(owner,scope);state['turns']=[]
            turn={'질문':question.strip() if follow else '리포트 생성','답변':'','완료':False,'출처':[],'오류':None}
            state['turns'].append(turn)
            progress=st.empty();progress.info('AgentStream 답변 생성 중…')
            live=st.empty()
            try:
                message=build_message(payload,question.strip() if follow else None)
                answer=Client(cfg).ask(state['conversation'],owner,scope,message,on_delta=lambda value:live.markdown(value))
                turn.update({'답변':answer.text,'완료':True,'출처':answer.references})
                progress.success('AgentStream 응답 완료')
            except AgentStreamError as exc:
                turn.update({'답변':exc.partial,'오류':str(exc)})
                progress.warning('AgentStream 응답 미완료 · '+str(exc))
            live.empty()
        for turn in state['turns']:
            st.markdown('**'+('리포트 생성' if turn['질문']=='리포트 생성' else '사용자 질문')+'**')
            if turn['질문']!='리포트 생성':st.write(turn['질문'])
            st.caption('AgentStream 실제 응답 · '+('완료' if turn['완료'] else '미완료'))
            if turn['답변']:st.markdown(turn['답변'])
            if turn['출처']:
                with st.expander('API에서 제공한 문서 근거'):
                    for source in turn['출처']:st.write(source)
            if turn['오류']:st.warning(turn['오류'])
        if state['turns']:
            last=state['turns'][-1]
            outcome={'방식':'AgentStream 실제 응답' if last['완료'] else ('AgentStream 부분 응답 + 규칙 기반 설명' if last['답변'] else '규칙 기반 설명 · AgentStream 미완료'),
                     '답변':last['답변'] or rule_summary(res,kind),'완료':last['완료'],'문서근거':last['출처'],'오류':last['오류']}
        if not state['turns'] or not state['turns'][-1]['완료']:
            st.caption('규칙 기반 설명 · 모델이 생성한 답변이 아닙니다.')
            st.markdown(TD.text(rule_summary(res,kind)))
    return outcome
