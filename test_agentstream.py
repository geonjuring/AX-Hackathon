import json
import os
from io import BytesIO
import unittest
from unittest.mock import patch
from datetime import date
import pandas as pd
from agentstream_client import (Config,Client,Conversation,AgentStreamError,parse_ndjson)
from agent import build_payload,build_message

BOT='767e55e3-53f4-4bd7-b1eb-533c0943df55'
SID='11111111-1111-4111-8111-111111111111'


def wire(*events):
    return ('\n'.join(json.dumps(e,ensure_ascii=False) for e in events)+'\n').encode()


class Response(BytesIO):
    def __init__(self,raw,status=200,content_type='application/json'):
        super().__init__(raw);self.status=status;self.headers={'Content-Type':content_type}


class Opener:
    def __init__(self,responses):self.responses=list(responses);self.requests=[]
    def open(self,req,timeout):
        self.requests.append(req)
        r=self.responses.pop(0)
        if isinstance(r,Exception):raise r
        return r


def healthy():return Response(b'{"status":"healthy","checked_at":"2026-11-07","embedding_models":[]}')
def session():return Response(json.dumps({'session_id':SID}).encode(),201)
def answer(text='확인 필요'):
    return Response(wire({'type':'assistant.delta','event_id':'1','data':{'content':text}},
                         {'type':'turn.completed','event_id':'2'}),content_type='application/x-ndjson')


class StreamTests(unittest.TestCase):
    def test_unicode_split_dedup_and_nontext_exclusion(self):
        raw=wire({'type':'tool.content','content':'도구 내부 정보'},
            {'type':'assistant.delta','event_id':'a','data':{'content':[{'type':'thinking','text':'숨긴 추론'}, {'type':'text','text':'한글 답변'}]}},
            {'type':'assistant.delta','event_id':'a','data':{'content':'중복'}},
            {'event':'turn.completed','data':{'sources':[{'document_name':'분석방법.docx','summary':'참고 집계','chunk_id':'비표시'}]}})
        a=parse_ndjson(raw[i:i+1] for i in range(len(raw)))
        self.assertEqual(a.text,'한글 답변')
        self.assertEqual(a.references,[{'document_name':'분석방법.docx','summary':'참고 집계'}])

    def test_partial_failure_eof_bad_json_and_tool_failure(self):
        for tail in [b'',b'not-json\n',wire({'type':'tool.failed'}),wire({'type':'turn.failed'})]:
            with self.subTest(tail=tail):
                raw=wire({'type':'assistant.delta','content':'이미 받은 답변'})+tail
                with self.assertRaises(AgentStreamError) as caught:parse_ndjson([raw])
                self.assertEqual(caught.exception.partial,'이미 받은 답변')

    def test_cancel_and_timeout(self):
        with self.assertRaises(AgentStreamError):parse_ndjson([b'{}\n'],cancel=lambda:True)
        with self.assertRaises(AgentStreamError):parse_ndjson([b'{}\n'],deadline=1)


class ContractTests(unittest.TestCase):
    def config(self):return Config(key='test-not-real')
    def test_contract_first_and_followup_same_session(self):
        opener=Opener([healthy(),session(),answer(),healthy(),answer('후속 답변')])
        client=Client(self.config(),opener);conv=Conversation('visitor','scope')
        self.assertEqual(client.ask(conv,'visitor','scope','첫 질문').text,'확인 필요')
        self.assertEqual(client.ask(conv,'visitor','scope','후속 질문').text,'후속 답변')
        requests=opener.requests
        self.assertEqual(len(requests),5)
        self.assertTrue(requests[0].full_url.endswith('/open/v1/chatbots/'+BOT+'/health'))
        self.assertEqual(json.loads(requests[1].data),{'query':'첫 질문'})
        self.assertEqual(json.loads(requests[2].data),{'message':'첫 질문'})
        self.assertEqual(json.loads(requests[4].data),{'message':'후속 질문'})
        self.assertEqual(requests[2].get_header('X-api-key'),'test-not-real')
        self.assertFalse(any(k in requests[2].headers for k in ['Cookie','Authorization','X-User-Id','X-Org-Id']))

    def test_key_missing_owner_mismatch_and_unhealthy_block_requests(self):
        for client,conv,who in [(Client(Config(),Opener([])),Conversation('a','s'),'a'),
                               (Client(self.config(),Opener([])),Conversation('a','s'),'b')]:
            with self.assertRaises(AgentStreamError):client.ask(conv,who,'s','질문')
            self.assertEqual(client.opener.requests,[])
        op=Opener([Response(b'{"status":"unhealthy"}')])
        with self.assertRaises(AgentStreamError):Client(self.config(),op).ask(Conversation('a','s'),'a','s','질문')
        self.assertEqual(len(op.requests),1)

    def test_403_html_and_failed_post_not_retried(self):
        from urllib.error import HTTPError
        op=Opener([HTTPError('https://example.test',403,'Forbidden',{},None)])
        with self.assertRaises(AgentStreamError) as caught:Client(self.config(),op).health()
        self.assertEqual(caught.exception.status,403)
        self.assertNotIn('test-not-real',str(caught.exception))
        op=Opener([Response(b'<html>login</html>',content_type='text/html')])
        with self.assertRaises(AgentStreamError):Client(self.config(),op).health()
        op=Opener([healthy(),session(),Response(wire({'type':'turn.failed'}),content_type='application/x-ndjson')])
        client=Client(self.config(),op);conv=Conversation('a','s')
        with self.assertRaises(AgentStreamError):client.ask(conv,'a','s','질문')
        self.assertTrue(conv.uncertain)
        with self.assertRaises(AgentStreamError):client.ask(conv,'a','s','질문')
        self.assertEqual(len(op.requests),3)

    def test_isolated_sessions_and_busy_lock(self):
        op=Opener([healthy(),session(),answer(),healthy(),session(),answer()])
        c=Client(self.config(),op)
        a,b=Conversation('a','s'),Conversation('b','s')
        c.ask(a,'a','s','질문');c.ask(b,'b','s','질문')
        self.assertEqual(sum(r.full_url.endswith('/sessions') for r in op.requests),2)
        a.lock.acquire()
        try:
            with self.assertRaises(AgentStreamError):c.ask(a,'a','s','다음 질문')
        finally:a.lock.release()

    def test_env_validation_and_legacy_key_not_used(self):
        with patch.dict(os.environ,{'AGENTSTREAM_API_KEY':'','AGENT_API_KEY':'legacy'},clear=True):
            self.assertEqual(Config.from_env().key,'')
        for key in ['prefix\nsecret','비ASCII']:
            with patch.dict(os.environ,{'AGENTSTREAM_API_KEY':key},clear=True):
                with self.assertRaises(AgentStreamError) as caught:Config.from_env()
                self.assertNotIn(key,str(caught.exception))
        for url in ['http://example.test','https://user:pass@example.test','https://example.test/open/v1']:
            with patch.dict(os.environ,{'AGENTSTREAM_BASE_URL':url},clear=True):
                with self.assertRaises(AgentStreamError):Config.from_env()


class PayloadTests(unittest.TestCase):
    def test_overview_keeps_null_and_values_and_no_system_override(self):
        p=build_payload({'overview':pd.DataFrame({'line':['01'],'값':[None]}),'기간':(date(2026,1,1),date(2026,1,2))},'overview')
        self.assertEqual(p['표']['호기별 집계'][0],{'line':'01','값':None})
        msg=build_message(p,'범위를 설명해주세요')
        self.assertNotIn('[보안 및 명령 우선순위]',msg)
        self.assertIn('null',msg)

    def test_payload_limits_fail_instead_of_truncating(self):
        for df in [pd.DataFrame({'x':range(2001)}),pd.DataFrame({str(i):[1] for i in range(31)}),pd.DataFrame({'x':['a'*1001]})]:
            with self.assertRaises(AgentStreamError):build_payload({'overview':df},'overview')

    def test_freeform_maintenance_example_not_sent(self):
        res={'line':'11','기간':(date(2026,1,1),date(2026,1,2)),
             '판정표':pd.DataFrame([{'항목':'설비 정비·특이사항 기록','판정':'있음','데이터':'예: 사람 이름 포함','근거':'일보'}]),
             '메모':pd.DataFrame({'내용':['사람 이름 포함']}),'요약':pd.Series({'kg_h':123.45})}
        p=build_payload(res,'equipment')
        self.assertNotIn('사람 이름 포함',json.dumps(p,ensure_ascii=False))
        self.assertEqual(p['표']['생산·효율 요약'][0]['kg_h'],123.45)


if __name__=='__main__':unittest.main()
