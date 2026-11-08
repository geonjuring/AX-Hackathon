"""Event-time historical replay, strictly separate from retrospective reports."""
from datetime import date, timedelta
import pandas as pd
import streamlit as st
import slp.analysis.lot_analysis as LA
import slp.analysis.forecast as F
import slp.common.table_display as TD
from slp.analysis.data_quality import snapshot, render_quality
from slp.reporting.export import render_download
from slp.common.number_format import number

VERSION = 'daily-linear-v1'


def end_of_production_day(day):
    return pd.Timestamp(day)+pd.Timedelta(days=1,hours=8,minutes=30)-pd.Timedelta(microseconds=1)


@st.cache_data(show_spinner=False)
def bounds(line):
    x=LA.q('SELECT min(p_date) a,max(p_date) b FROM feeder WHERE line=?',[str(line)]).iloc[0]
    return LA.pdate(x['a']).date(),LA.pdate(x['b']).date()


@st.cache_data(show_spinner=False)
def predict(kind, identity, day):
    cutoff=end_of_production_day(day)
    if kind=='lot':
        info=LA.q('SELECT line,grade,color FROM plan WHERE lot_no=? LIMIT 1',[str(identity)])
        if info.empty:
            return {'예측':pd.DataFrame(),'보류':'LOT의 호기·제품 정보가 없습니다.'}
        i=info.iloc[0].to_dict()
        i.update(ts_end=cutoff,p_last=day.strftime('%Y.%m.%d'))
        return F.analyze({'info':i},'lot')
    return F.analyze({'line':identity,'기간':(day-timedelta(days=59),day)},'equipment')


@st.cache_data(show_spinner=False)
def actuals(line, grade, color, day):
    cutoff=end_of_production_day(day)
    cols=', '.join(f'quantile_cont(f.{col},0.5) "{name}"' for name,col in F.METRICS.items())
    d=LA.q(f'''SELECT f.p_date 일자,count(*) 기록수,{cols} FROM feeder f WHERE f.line=?
        AND f.p_date BETWEEN ? AND ? AND f.ts>? AND f.mval02>={LA.RUN_RPM}
        AND EXISTS(SELECT 1 FROM plan p WHERE p.lot_no=f.lot_no AND p.grade=? AND p.color=?)
        GROUP BY f.p_date HAVING count(*)>=60 ORDER BY f.p_date''',
        [line,(day+timedelta(days=1)).strftime('%Y.%m.%d'),(day+timedelta(days=3)).strftime('%Y.%m.%d'),cutoff,grade,color])
    d['예측일']=pd.to_datetime(d.pop('일자').str.replace('.','-',regex=False)).dt.date
    return d.melt(id_vars=['예측일','기록수'],var_name='항목',value_name='이후 실측').dropna(subset=['이후 실측'])


def evaluate(predictions, observed):
    if predictions.empty:
        return observed.assign(비교상태='예측 보류 · 오차 산정 불가')
    d=predictions.merge(observed,on=['예측일','항목'],how='left')
    # An empty merge yields object dtype in pandas 2.x. Preserve missing
    # observations as NaN while making error arithmetic explicitly numeric.
    d['이후 실측']=pd.to_numeric(d['이후 실측'],errors='coerce')
    d['절대오차']=(d['참고 예측값']-d['이후 실측']).abs().round(3)
    d['비교상태']=d['이후 실측'].notna().map({True:'비교 가능',False:'이후 동일 제품 실측 없음'})
    d['참고범위 내 여부']=[('범위 내' if lo<=v<=hi else '범위 밖') if pd.notna(v) else '비교 불가'
                           for lo,v,hi in zip(d['참고 하한'],d['이후 실측'],d['참고 상한'])]
    return d


def render(kind, identity, line, default_day):
    a,b=bounds(line)
    if pd.isna(a) or pd.isna(b):
        st.info('재생할 운전 기록이 없습니다.');return
    key=f'replay:{kind}:{identity}'
    if key+'day' not in st.session_state:
        st.session_state[key+'day']=max(a,min(b,default_day))
    with st.sidebar:
        st.subheader('과거 사례 재생')
        left,right=st.columns(2)
        if left.button('이전 1일',key=key+'prev',disabled=st.session_state[key+'day']<=a):
            st.session_state[key+'day']-=timedelta(days=1)
        if right.button('다음 1일',key=key+'next',disabled=st.session_state[key+'day']>=b):
            st.session_state[key+'day']+=timedelta(days=1)
        day=st.date_input('재생 기준 생산일',min_value=a,max_value=b,key=key+'day')
        reveal=st.checkbox('이후 실제 결과 공개',value=False,key=key+str(day)+'reveal')
    cutoff=end_of_production_day(day)
    st.title(f'{"LOT "+str(identity) if kind=="lot" else str(line)+"호기 설비"} · 과거 사례 재생')
    st.caption(f'기준 생산일 {day} · 운전 기록 마감 {cutoff} · 예측 버전 {VERSION}')
    st.info('운전 기록 발생 시각을 기준으로 재생합니다. 당시 자료 입수 시각·수정 이력은 복원하지 않으며, 선택한 LOT의 호기·제품 정보는 고정 조건으로 사용합니다. 이후 실측은 공개했을 때만 조회하며 예측 입력에는 사용하지 않습니다.')
    f=predict(kind,str(identity),day)
    if '호기' not in f:
        f = {**f, '호기': str(line), 'Grade': None, 'Color': None, '제품': f'{line}호기 · 제품조건 확인 불가'}
    quality=snapshot(str(line),day-timedelta(days=59),day,cutoff=cutoff,grade=f['Grade'],color=f['Color'])
    render_quality(quality)
    st.caption('재생 품질 요약은 마감 이전 60일의 동일 제품 기록입니다. 시각이 없는 운전 기록은 재생 시점을 정할 수 없어 제외합니다. 생산실적은 입력 시각도 마감 이전인 기록만 사용합니다.')
    from slp.ui.aistream_panel import render as render_pattern
    from slp.ai.aistream.analysis import Selection, export_parts
    pattern_selection = (Selection.lot_scope(identity, cutoff) if kind == 'lot' else
                         Selection.period(day-timedelta(days=59), day, line=str(line), cutoff=cutoff))
    pattern = render_pattern(pattern_selection)
    st.subheader('재생 시점의 예측')
    st.write(f"동일 제품 조건: {f['제품']}")
    if f['보류']:
        st.warning(f['보류'])
    else:
        TD.show(f['예측'],hide_index=True,width='stretch')
    with st.expander('마감 이전 예측 입력 이력'):
        TD.show(f.get('이력',pd.DataFrame()),hide_index=True,width='stretch')
    comparison=pd.DataFrame()
    if reveal:
        st.subheader('이후 실제 결과와 비교')
        if f['Grade'] is not None and f['Color'] is not None:
            comparison=evaluate(f['예측'],actuals(str(line),f['Grade'],f['Color'],day))
        if comparison.empty:
            st.info('이후 3일에 같은 제품의 유효 실측이 없습니다. 예측 오차를 계산하지 않습니다.')
        else:
            TD.show(comparison,hide_index=True,width='stretch')
            if '절대오차' in comparison:
                metric_errors=comparison.dropna(subset=['절대오차']).groupby('항목',as_index=False).agg(평균절대오차=('절대오차','mean'),비교건수=('절대오차','size'))
                st.caption('항목별 단위가 다르므로 오차는 항목별로 표시합니다. 참고범위 포함 여부는 고장·불량 판정이 아닙니다.')
                TD.show(metric_errors,hide_index=True,width='stretch')
    else:
        st.caption('이후 실측은 숨김 상태입니다. 왼쪽에서 공개하면 예측값을 고정한 채 뒤의 실측과 비교합니다.')
    from slp.ui.agent_panel import render as render_agent
    ai_result = render_agent({'line': str(line), 'lot': identity if kind == 'lot' else None, 'AIStream': pattern,
        '기간': (day-timedelta(days=59),day), '데이터품질': quality,
        '재생조건': {'마감시각': cutoff, '제품': f['제품'], '이후 실측은 모델 입력에서 제외': True},
        'tables': {'마감 이전 입력 이력': f.get('이력',pd.DataFrame())}}, 'replay', f)
    from slp.ui.demo_alarm import render_alarm
    context=key+':'+str(day)
    render_alarm(f,context)
    paragraphs={'예측 해석':'같은 호기·Grade·Color가 지속될 때의 다음 3일 선형 추세입니다. 참고범위는 회귀 잔차 ±2배이며 검증된 신뢰구간·고장확률이 아닙니다.',
                '권장 조치':'다음 생산 시작 시 운전값을 재측정하고 같은 제품의 설정값·부하·정비 상태를 확인하세요. 예측 보류 시 동일 조건의 이력을 보완하세요.',
                '종합 주의사항':'재생은 기록 발생 시각 기준이며 당시 자료 입수·수정 이력을 복원하지 않습니다. 미확정 기준과 데이터 부족을 먼저 확인하세요. 가상 인원·역할을 사용한 모의 알림이며 실제 메시지는 발송되지 않습니다.'}
    paragraphs = {'AgentStream 설명 ('+ai_result['방식']+')': ai_result['답변'], **paragraphs}
    tables={'데이터 품질 요약':pd.DataFrame([quality['요약']]),'수치 누락 상세':quality['누락'],'기록 부족 교대':quality['교대'],
            '예측 입력 이력':f.get('이력',pd.DataFrame()),'예측 결과':f['예측']}
    if reveal:
        tables['이후 실측 비교']=comparison
    pattern_meta, pattern_tables, pattern_paragraphs = export_parts(pattern)
    tables.update(pattern_tables)
    paragraphs = {**pattern_paragraphs, **paragraphs}
    render_download(f'{identity}_{kind}_과거재생_{day}',{'모드':'과거 사례 재생','기준 생산일':day,'마감시각':cutoff,
        '제품':f['제품'],'예측 버전':VERSION,'예측 보류 이유':f['보류'],'이후 실측 공개':reveal, 'AgentStream 완료':ai_result['완료'], 'AgentStream 방식':ai_result['방식'], 'AgentStream 문서근거':ai_result.get('문서근거'), 'AgentStream 오류':ai_result.get('오류'), **pattern_meta},tables,paragraphs,context,
        st.session_state.get('demo_alarm:'+context))
    st.subheader('종합 주의사항')
    st.write(paragraphs['종합 주의사항'])
    st.write(paragraphs['예측 해석'])
    st.write(paragraphs['권장 조치'])
