"""Analysis context and offline fallback; server chatbot owns its system prompt."""
import hashlib
import json
import pandas as pd
from slp.reporting.export import clean
from slp.ai.agentstream.client import AgentStreamError, Client, Conversation, MAX_BYTES


def _tables(res,kind,forecast=None):
    if kind=='overview':
        tables={'호기별 집계':res['overview']}
    elif kind=='replay':
        tables=dict(res.get('tables',{}))
    else:
        names=['판정표','생산정보','공정불량','계량','믹서','공정조건','배럴'] if kind=='lot' else ['판정표','Grade','배럴','전력']
        tables={name:res[name] for name in names if isinstance(res.get(name),pd.DataFrame)}
        # Do not send free-form maintenance notes or raw action descriptions.
        tables={name:frame.drop(columns=['조치내용','내용'],errors='ignore') for name,frame in tables.items()}
        if kind=='equipment':
            tables['생산·효율 요약']=pd.DataFrame([res['요약']])
            if '판정표' in tables:
                judge=tables['판정표'].copy()
                mask=judge['항목'].str.contains('정비·특이사항',regex=False)
                judge.loc[mask,'데이터']=judge.loc[mask,'판정'].map({'있음':'기록 있음','없음':'기록 없음'}).fillna('기록 확인 필요')
                tables['판정표']=judge
    quality=res.get('데이터품질')
    if isinstance(quality,dict):
        tables['주요값 누락']=quality.get('누락',pd.DataFrame())
    if forecast is not None:
        tables['참고 예측값']=forecast['예측']
    return tables


def build_payload(res,kind='lot',forecast=None):
    tables=_tables(res,kind,forecast)
    cells=0
    for name,table in tables.items():
        if not isinstance(table,pd.DataFrame):
            raise AgentStreamError('전달할 표의 형식을 확인하세요.',stage='input')
        rows,cols=table.shape;cells+=rows*cols
        if rows>2000 or cols>30 or any(len(str(c))>100 for c in table.columns):
            raise AgentStreamError('표의 2,000행·30열·열 이름 100자 제한을 초과합니다. 범위를 줄여주세요.',stage='input')
        for value in table.to_numpy().flat:
            if isinstance(value,str) and len(value)>1000:
                raise AgentStreamError('표에 1,000자 초과 텍스트가 있습니다. 전달 항목을 조정하세요.',stage='input')
    if cells>20000:
        raise AgentStreamError('전체 20,000셀 제한을 초과합니다. 범위를 줄여주세요.',stage='input')
    quality=res.get('데이터품질',{})
    metadata={'분석유형':kind,'LOT':res.get('lot'),'호기':res.get('line') or res.get('info',{}).get('line'),
        '기간':res.get('기간'),'비교LOT':res.get('비교'),'기준기간':res.get('기준기간'),
        '출처':'서버의 slp.duckdb에서 계산한 선택 범위 집계. 실시간 MES 직접 조회 아님.',
        '데이터품질':quality.get('요약') if isinstance(quality,dict) else None,
        '단위':{'생산량':'kg 또는 열에 명시한 t','가동시간':'h','RPM':'RPM','온도':'℃','전력':'kW / kWh / kWh/t',
                '전류·진공·물성·원료계량 수량':'원천 단위 미확인. 임의 단위 치환 금지'},
        '필터':'가동 RPM>=250. 배럴 ±10℃는 참고 집계. 세부 비교 조건은 등록된 분석방법 문서 참조.',
        '자료구분':'관측·집계와 참고 예측을 분리. null은 결측이며 0과 다름.'}
    if kind=='lot':
        metadata.update({'Grade':res['info'].get('grade'),'Color':res['info'].get('color'),
                         '운전범위':(res['info'].get('ts_start'),res['info'].get('ts_end'))})
    if forecast is not None:
        metadata['예측정보']={k:forecast.get(k) for k in ('제품','기준시각','보류')}
        metadata['예측해석']='daily-linear-v1 로컬 선형 추세. 동일 조건 지속 가정, 잔차 ±2배 참고범위. AIStream 연동 모델·고장확률·검증된 신뢰구간 아님.'
    if kind=='replay': metadata['재생조건']=res.get('재생조건')
    pattern = res.get('AIStream')
    if isinstance(pattern, dict):
        metadata['AIStream 운전 패턴'] = {'종류': '관측 구간의 운전 패턴 분석. 미래 예측·고장 확률·현장 판정 아님.',
            '완료': pattern.get('완료', False), '요약': pattern.get('요약'),
            '보류': pattern.get('보류'), '오류': pattern.get('오류')}
        from slp.ai.aistream.analysis import tables as pattern_tables
        windows = pattern_tables(pattern)['AIStream 구간별 결과']
        if not windows.empty:
            candidates = windows[windows['상태'].eq('패턴 이상 후보')]
            tables['AIStream 이상 후보 (최대 20개)'] = candidates.head(20)
            metadata['AIStream 운전 패턴']['후보표 범위'] = 'API가 반환한 이상 후보 중 최대 20개만 설명에 전달. 전체 구간은 화면·다운로드 참조.'
    payload=clean({'분석조건':metadata,'표':tables})
    if len(json.dumps(payload,ensure_ascii=False,allow_nan=False).encode())>MAX_BYTES:
        raise AgentStreamError('분석 결과가 UTF-8 1MiB 제한을 초과합니다. 범위를 줄여주세요.',stage='input')
    return payload


def build_message(payload,question=None):
    task=question or '선택된 분석 결과를 설명하고 필요한 문서 근거를 검색하여 리포트를 작성해주세요. 자료 부족·판정 보류·예측 한계를 구분하고 종합 주의사항으로 마무리해주세요.'
    # These are already calculated, heterogeneous reports, not one raw table
    # for AgentStream's single-table analysis pipeline. Send a readable text
    # context with explicit table/row provenance, retaining every scalar value.
    lines=[task,'','현재 앱 계산 결과 — 관측·집계·참고예측 자료',
           '아래는 앱이 계산한 여러 보고서의 설명 문맥입니다. 표별로 행을 구분합니다. 한 표가 비어 있어도 다른 표까지 비었다는 뜻이 아닙니다. null은 결측이며 숫자 0과 다릅니다.',
           '', '분석조건 설명']
    def value_text(value):
        if value is None:return '결측(null)'
        if isinstance(value,bool):return 'true' if value else 'false'
        if isinstance(value,str):return value.replace('\r',' ').replace('\n',' ')
        return str(value)
    def describe(path,value):
        if isinstance(value,dict):
            if not value:lines.append('- '+path+'에는 항목이 없습니다.')
            for key,child in value.items():describe(path+' > '+str(key),child)
        elif isinstance(value,(list,tuple)):
            if not value:lines.append('- '+path+'에는 목록이 없습니다.')
            for index,child in enumerate(value,1):describe(path+' > '+str(index),child)
        else:
            lines.append('- 분석조건의 '+path+' 값은 '+value_text(value)+' 입니다.')
    for name,value in payload.get('분석조건',{}).items():describe(name,value)
    total_rows=sum(len(records) for records in payload.get('표',{}).values())
    if total_rows>2000:
        raise AgentStreamError('전달할 표의 합계가 2,000행을 초과합니다. 분석 범위를 줄여주세요.',stage='input')
    for name,records in payload.get('표',{}).items():
        lines.extend(['','분석표 '+name+'의 원래 행수는 '+str(len(records))+' 입니다.'])
        if not records:lines.append('- 데이터 행이 없습니다. 이 표에만 해당합니다.')
        for index,record in enumerate(records,1):
            for column,value in record.items():
                lines.append('- '+name+'의 '+str(index)+'번째 행에서 '+str(column)+' 값은 '+value_text(value)+' 입니다.')
    message='\n'.join(lines)
    if len(message.encode('utf8'))>MAX_BYTES:
        raise AgentStreamError('질문과 API 표가 UTF-8 1MiB 제한을 초과합니다. 범위를 줄여주세요.',stage='input')
    return message


def payload_id(payload):
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def rule_summary(res,kind='lot'):
    if kind=='overview':
        return '선택 기간의 호기별 집계와 데이터 품질을 비교하세요. 기록 공백·누락, 불량·정지 기록이 있는 호기는 개별 상세에서 원천 기록과 조치 완료 여부를 확인하세요. 제품 구성·호기 용량이 달라 효율 순위만으로 이상을 확정할 수 없습니다.'
    if kind=='replay':
        return '마감 이전 운전 기록으로 계산한 참고 추세입니다. 관측일 부족이면 예측을 보류하며, 이후 실측은 공개한 경우에만 별도로 비교합니다. 원인·고장·불량 확률을 확정하지 않습니다.'
    j=res['판정표'];have=j[j['판정']=='있음'];tbd=j[j['판정']=='기준 미정']
    target=f"LOT {res['lot']}" if kind=='lot' else f"{res['line']}호기 · {res['기간'][0]} ~ {res['기간'][1]}"
    lines=[target+' 데이터 대조 결과입니다.']
    lines.append('기록 확인: '+' / '.join(f"{r['항목']} — {r['데이터']}" for _,r in have.iterrows()) if len(have) else '현재 대조 가능한 항목에서 확인된 이탈·이상 기록은 없습니다. 미측정 항목은 별도 확인이 필요합니다.')
    if len(tbd):lines.append('비교 결과(현장 판정기준 미정): '+' / '.join(f"{r['항목']} — {r['데이터']}" for _,r in tbd.iterrows()))
    missing=j[j['판정'].isin(['데이터 없음','데이터 부족'])]
    if len(missing):lines.append('확인 불가(자료 보완 필요): '+' / '.join(missing['항목']))
    lines.append('종합 주의사항: 원인 판단이 아닌 데이터 대조 결과입니다. 다음 생산 전 현장 재측정·승인 기준·조치 완료 여부를 확인하세요.')
    return '\n\n'.join(lines)


def call_agentstream(prompt):
    client=Client();owner='one-shot';scope=client.config.signature()
    return client.ask(Conversation(owner,scope),owner,scope,prompt).text


def ai_summary(res,question=None,kind='lot',forecast=None):
    try:
        return call_agentstream(build_message(build_payload(res,kind,forecast),question)),True
    except AgentStreamError as exc:
        return rule_summary(res,kind)+'\n\n(규칙 기반 설명 · '+str(exc)+')',False
