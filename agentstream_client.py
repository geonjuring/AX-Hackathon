"""AgentStream /open/v1 client. No login cookies, prompt override, or POST retries."""
from dataclasses import dataclass, field
from http.client import HTTPException
import codecs
import hashlib
import json
import logging
import os
import socket
import threading
import time
from urllib import request, error, parse
from uuid import UUID, uuid4

DEFAULT_BASE = 'https://api-gateway.jntp-ax.or.kr/agentstream'
DEFAULT_BOT = 'de8ab940-c114-45a8-a9f6-a38a0b33d1d2'
DEFAULT_WORKSPACE = '4e1ef8d1-2bf7-4469-8fa0-b2431771a36a'
MAX_BYTES = 1024 * 1024
LOGGER = logging.getLogger(__name__)


class AgentStreamError(Exception):
    def __init__(self, message, *, stage='configuration', partial='', status=None):
        super().__init__(message)
        self.stage, self.partial, self.status = stage, partial, status


@dataclass(frozen=True)
class Config:
    base: str = DEFAULT_BASE
    chatbot: str = DEFAULT_BOT
    workspace: str = DEFAULT_WORKSPACE
    key: str = field(default='', repr=False)
    timeout: float = 60

    @classmethod
    def from_env(cls):
        try:
            timeout = float(os.environ.get('AGENTSTREAM_TIMEOUT_SECONDS') or 60)
        except ValueError:
            raise AgentStreamError('호출 대기시간 설정을 확인하세요.') from None
        if not 1 <= timeout <= 300:
            raise AgentStreamError('호출 대기시간은 1초부터 300초까지 설정하세요.')
        cfg=cls(base=(os.environ.get('AGENTSTREAM_BASE_URL') or DEFAULT_BASE).rstrip('/'),
                chatbot=os.environ.get('AGENTSTREAM_CHATBOT_ID') or DEFAULT_BOT,
                workspace=os.environ.get('AGENTSTREAM_WORKSPACE_ID') or DEFAULT_WORKSPACE,
                key=os.environ.get('AGENTSTREAM_API_KEY','').strip(), timeout=timeout)
        if any(ord(c)<33 or ord(c)>126 for c in cfg.key):
            raise AgentStreamError('API 키에 공백·제어문자·비 ASCII 문자가 있습니다. 입력을 확인하세요.')
        u=parse.urlsplit(cfg.base)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise AgentStreamError('AgentStream 서버 주소는 인증정보·쿼리 없는 HTTPS 주소여야 합니다.')
        if '/open/v1' in u.path:
            raise AgentStreamError('서버 기본 주소에 /open/v1을 중복 지정하지 마세요.')
        for value in (cfg.chatbot,cfg.workspace):
            try: UUID(value)
            except (ValueError,TypeError):
                raise AgentStreamError('챗봇·워크스페이스 UUID 설정을 확인하세요.') from None
        return cfg

    def signature(self):
        return hashlib.sha256((self.base+self.chatbot+self.workspace+self.key).encode()).hexdigest()


@dataclass
class Conversation:
    owner: str
    scope: str
    session_id: str | None = None
    lock: object = field(default_factory=threading.Lock, repr=False)
    uncertain: bool = False


@dataclass
class Answer:
    text: str
    references: list = field(default_factory=list)


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def error_message(status):
    return {401:'API 키가 없거나 유효하지 않습니다.',403:'챗봇 공개·키 발급 워크스페이스·CHAT_INVOKE 권한 매핑을 확인하세요.',
            404:'API 기본 경로와 챗봇·세션 UUID를 확인하세요.',422:'query/message 요청 형식과 Content-Type을 확인하세요.',
            429:'호출 한도를 초과했습니다. 잠시 후 사용자가 다시 시도하세요.',503:'서비스가 일시적으로 사용 불가합니다.'}.get(status,'외부 API 요청을 완료하지 못했습니다.')


def text_blocks(content):
    if isinstance(content,str): return content
    if isinstance(content,list):
        return ''.join(b['text'] for b in content if isinstance(b,dict) and b.get('type')=='text' and isinstance(b.get('text'),str))
    raise AgentStreamError('응답 텍스트 형식이 올바르지 않습니다.',stage='message')


def parse_ndjson(chunks, on_delta=None, cancel=None, deadline=None):
    decoder=codecs.getincrementaldecoder('utf-8')('strict')
    buffer=''; pieces=[]; seen=set(); refs=[]; completed=False; size=0
    def consume(line):
        nonlocal completed
        if not line.strip(): return
        try: event=json.loads(line)
        except (ValueError,TypeError):
            raise AgentStreamError('응답 스트림에 잘못된 JSON이 있습니다.',stage='message') from None
        if not isinstance(event,dict):
            raise AgentStreamError('응답 이벤트 형식이 올바르지 않습니다.',stage='message')
        event_id=event.get('event_id')
        if event_id is not None:
            if not isinstance(event_id,(str,int)):
                raise AgentStreamError('이벤트 ID 형식을 확인할 수 없습니다.',stage='message')
            if event_id in seen: return
            seen.add(event_id)
        # The gateway uses `event` for the stream event and `type` for the
        # underlying message class (e.g. AIMessageChunk or tool).
        name=event.get('event') or event.get('type')
        data=event.get('data',event)
        if not isinstance(data,dict): data={}
        if name in ('turn.failed','tool.failed'):
            raise AgentStreamError('챗봇 또는 연결 도구 실행이 실패했습니다. 자동 재전송하지 않았습니다.',stage='message')
        if name=='assistant.delta':
            if completed:
                raise AgentStreamError('완료 이후 응답이 추가되어 결과를 검증할 수 없습니다.',stage='message')
            token=text_blocks(data.get('content',''))
            pieces.append(token)
            if on_delta and token: on_delta(''.join(pieces))
        if name in ('assistant.delta','turn.completed'):
            # Preserve only explicitly supplied source metadata, never synthesize it.
            for key in ('sources','citations'):
                source=data.get(key)
                if isinstance(source,list):
                    for item in source:
                        if isinstance(item,dict):
                            allowed={k:v for k,v in item.items() if k in ('document_name','title','summary','url') and isinstance(v,str)}
                            if allowed and allowed not in refs: refs.append(allowed)
        if name=='turn.completed': completed=True
    try:
        for chunk in chunks:
            if cancel and cancel():
                raise AgentStreamError('요청을 취소했습니다. 부분 응답은 보존했습니다.',stage='message')
            if deadline and time.monotonic()>deadline:
                raise AgentStreamError('응답 대기시간을 초과했습니다.',stage='message')
            size+=len(chunk)
            if size>8*MAX_BYTES:
                raise AgentStreamError('응답 크기 제한을 초과했습니다.',stage='message')
            buffer+=decoder.decode(chunk)
            while '\n' in buffer:
                line,buffer=buffer.split('\n',1);consume(line.rstrip('\r'))
            if completed:
                buffer=''
                break
        if not completed: buffer+=decoder.decode(b'',final=True)
        if buffer.strip(): consume(buffer)
        if not completed:
            raise AgentStreamError('정상 완료 이벤트 없이 연결이 종료됐습니다.',stage='message')
        if not ''.join(pieces).strip():
            raise AgentStreamError('완료 이벤트는 받았지만 답변 텍스트가 없습니다.',stage='message')
        return Answer(''.join(pieces),refs)
    except AgentStreamError as exc:
        exc.partial=''.join(pieces);raise
    except (UnicodeError,OSError,HTTPException):
        raise AgentStreamError('응답 수신 중 연결·문자 인코딩 오류가 발생했습니다.',stage='message',partial=''.join(pieces)) from None


class Client:
    def __init__(self,config=None,opener=None):
        self.config=config or Config.from_env()
        self.opener=opener or request.build_opener(NoRedirect())

    def _open(self,path,stage,body=None):
        cfg=self.config
        if not cfg.key:
            raise AgentStreamError('API 키 미설정 · 현재는 규칙 기반 설명을 사용합니다.')
        raw=None if body is None else json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf-8')
        if raw is not None and len(raw)>MAX_BYTES:
            raise AgentStreamError('요청이 UTF-8 1MiB 제한을 초과합니다. 범위를 줄여주세요.',stage=stage)
        headers={'X-API-Key':cfg.key,'Accept':'application/x-ndjson' if stage=='message' else 'application/json'}
        if raw is not None: headers['Content-Type']='application/json'
        req=request.Request(cfg.base+path,data=raw,headers=headers,method='GET' if body is None else 'POST')
        started=time.monotonic()
        try:
            response=self.opener.open(req,timeout=cfg.timeout)
        except error.HTTPError as exc:
            status=exc.code;exc.close()
            LOGGER.warning('AgentStream stage=%s http=%s elapsed=%.2fs',stage,status,time.monotonic()-started)
            raise AgentStreamError(error_message(status),stage=stage,status=status) from None
        except (OSError,error.URLError,HTTPException):
            raise AgentStreamError('서버의 DNS·TLS·통신 상태 또는 응답 대기시간을 확인하세요.',stage=stage) from None
        LOGGER.info('AgentStream stage=%s http=%s elapsed=%.2fs',stage,response.status,time.monotonic()-started)
        expected=201 if stage=='session' else 200
        status=response.status
        typ=response.headers.get('Content-Type','').split(';',1)[0].strip().lower()
        required='application/x-ndjson' if stage=='message' else 'application/json'
        if status!=expected or typ!=required:
            response.close()
            raise AgentStreamError('API 응답 상태·Content-Type이 예상과 다릅니다. HTML 로그인·관문 오류 여부를 확인하세요.',stage=stage,status=status)
        return response

    def _json(self,path,stage,body=None):
        with self._open(path,stage,body) as response:
            try:
                raw=response.read(MAX_BYTES+1)
                if len(raw)>MAX_BYTES: raise ValueError()
                payload=json.loads(raw.decode('utf-8'))
                if not isinstance(payload,dict): raise ValueError()
                return payload
            except (ValueError,UnicodeError,OSError,HTTPException):
                raise AgentStreamError('API JSON 응답을 읽을 수 없습니다.',stage=stage) from None

    def health(self):
        d=self._json(f'/open/v1/chatbots/{self.config.chatbot}/health','health')
        if d.get('status') not in ('healthy','unhealthy','unknown'):
            raise AgentStreamError('연결 상태 응답에 유효한 status가 없습니다.',stage='health')
        return {'status':d['status'],'message':str(d.get('message') or '').replace(self.config.key,'[비밀값 제외]') if self.config.key else '', 'checked_at':d.get('checked_at'),'embedding_models':d.get('embedding_models')}

    def ask(self,conversation,owner,scope,message,on_delta=None,cancel=None):
        if conversation.owner!=owner or conversation.scope!=scope:
            raise AgentStreamError('현재 방문자의 대화 범위와 일치하지 않습니다.',stage='session')
        if not conversation.lock.acquire(blocking=False):
            raise AgentStreamError('같은 대화의 이전 요청이 처리 중입니다.',stage='session')
        try:
            if conversation.uncertain:
                raise AgentStreamError('이전 요청의 완료를 확인하지 못했습니다. 새 대화로 다시 시작하세요.',stage='session')
            if len(message.encode('utf-8'))>MAX_BYTES:
                raise AgentStreamError('질문과 데이터가 1MiB 제한을 초과합니다.',stage='message')
            if cancel and cancel():
                raise AgentStreamError('요청을 취소했습니다.',stage='message')
            health=self.health()
            if health['status']!='healthy':
                raise AgentStreamError('모델·도구 상태가 '+health['status']+'여서 호출을 보류했습니다.',stage='health')
            if not conversation.session_id:
                d=self._json(f'/open/v1/chatbots/{self.config.chatbot}/sessions','session',{'query':message})
                sid=d.get('session_id')
                try: UUID(sid)
                except (ValueError,TypeError,AttributeError):
                    raise AgentStreamError('세션 생성 응답에 유효한 session_id가 없습니다.',stage='session') from None
                conversation.session_id=sid
            try:
                with self._open(f'/open/v1/chat-sessions/{conversation.session_id}/messages','message',{'message':message}) as response:
                    def chunks():
                        while True:
                            part=response.read1(8192) if hasattr(response,'read1') else response.read(8192)
                            if not part: break
                            yield part
                    return parse_ndjson(chunks(),on_delta,cancel,time.monotonic()+self.config.timeout)
            except BaseException:
                # A Streamlit stop/rerun also leaves the upstream turn uncertain.
                conversation.uncertain=True
                raise
        finally:
            conversation.lock.release()
