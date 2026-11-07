"""Batch overview across every known line; differences are not defect judgments."""
from datetime import timedelta
import pandas as pd
import streamlit as st
import altair as alt
import equip_analysis as EA
from lot_analysis import q,RUN_RPM
import table_display as TD
from report_export import render_download
from replay import end_of_production_day


@st.cache_data(show_spinner='전체 호기 분석 중…')
def analyze(a,b,cutoff=None):
    args=[EA.ds(a),EA.ds(b)]
    fw='p_date BETWEEN ? AND ?'; pw=fw
    fa=list(args);pa=list(args)
    if cutoff is not None:
        fw+=' AND ts<=?';fa.append(cutoff)
        pw+=' AND input_dt<=?';pa.append(cutoff)
    prod=q(f'SELECT line,sum(pr_qty) kg FROM result WHERE {pw} GROUP BY line',pa)
    rec=q(f'''SELECT line,count(*) 기록수,count(*) FILTER(WHERE mval02>={RUN_RPM}) n_run,
        max(ts) 최종기록,count(*) FILTER(WHERE ts IS NULL) 시각누락,
        count(*) FILTER(WHERE mval02 IS NULL OR NOT isfinite(mval02) OR mval03 IS NULL OR NOT isfinite(mval03)
          OR mval01 IS NULL OR NOT isfinite(mval01) OR cval08 IS NULL OR NOT isfinite(cval08)) 주요값누락기록
        FROM feeder WHERE {fw} GROUP BY line''',fa)
    events=q(f'''WITH ordered AS (
        SELECT line,ts,coalesce(mval02,0)>={RUN_RPM} running,
        lag(coalesce(mval02,0)>={RUN_RPM}) OVER(PARTITION BY line ORDER BY ts) prev_running,
        lag(ts) OVER(PARTITION BY line ORDER BY ts) prev_ts FROM feeder WHERE {fw} AND ts IS NOT NULL),
        grouped AS (SELECT *,sum(CASE WHEN running IS DISTINCT FROM prev_running THEN 1 ELSE 0 END)
        OVER(PARTITION BY line ORDER BY ts ROWS UNBOUNDED PRECEDING) grp FROM ordered),
        stops AS (SELECT line,grp,round_even(date_diff('microsecond',min(ts),max(ts))/60000000.0+1,0) duration_min
        FROM grouped WHERE NOT running GROUP BY line,grp HAVING duration_min>={EA.STOP_MIN}),
        sa AS (SELECT line,count(*) 정지횟수,sum(duration_min)/60 정지시간_h FROM stops GROUP BY line),
        ga AS (SELECT line,count(*) FILTER(WHERE date_diff('microsecond',prev_ts,ts)/60000000.0>={EA.GAP_MIN}) 기록공백 FROM ordered GROUP BY line)
        SELECT * FROM ga FULL JOIN sa USING(line)''',fa)
    short=q(f'''WITH shifts AS (SELECT line,p_date,CASE WHEN strftime(ts,'%H%M')>='0830' AND strftime(ts,'%H%M')<'2030'
        THEN '1' ELSE '2' END juya,count(*) n FROM feeder WHERE {fw} GROUP BY ALL),
        production AS (SELECT line,p_date,juya,sum(pr_qty) kg FROM result WHERE {pw} GROUP BY ALL HAVING kg>0)
        SELECT p.line,count(*) 부족교대 FROM production p LEFT JOIN shifts f USING(line,p_date,juya)
        WHERE coalesce(f.n,0)<{EA.SHIFT_MIN_REC} GROUP BY p.line''',fa+pa)
    bad=q('SELECT line,count(*) 불량기록,sum(bad_qty) 불량수량_kg FROM quality WHERE q_date BETWEEN ? AND ? GROUP BY line',args)
    table=q('SELECT DISTINCT line FROM lot_run WHERE line IS NOT NULL UNION SELECT DISTINCT line FROM result WHERE line IS NOT NULL')
    for d in (prod,rec,events,short,bad):
        table=table.merge(d,on='line',how='outer')
    for col in ['기록수','n_run','시각누락','주요값누락기록','정지횟수','정지시간_h','기록공백','부족교대','불량기록','불량수량_kg']:
        table[col]=table[col].fillna(0)
    table['생산량_t']=(table['kg']/1000).round(1)
    table['가동시간_h']=table['n_run']/60
    table['가동률_%']=(table['가동시간_h']/(((b-a).days+1)*24)*100).where(table['기록수']>0).round(1)
    table['kg_h']=(table['kg']/table['가동시간_h']).where(table['가동시간_h']>0).round(1)
    table['확인사항']=[('운전 기록 없음 · 데이터 확인 필요' if r['기록수']==0 else
        ' / '.join(label for key,label in [('주요값누락기록','운전값 누락'),('기록공백','기록 공백'),('부족교대','기록 부족 교대'),('불량기록','불량 기록'),('정지횟수','정지 기록')] if r[key]>0) or '집계된 이탈·기록 없음')
        for r in table.to_dict('records')]
    return table.sort_values('line',key=lambda s:pd.to_numeric(s,errors='coerce')).reset_index(drop=True)


def render(a,b,mode):
    day=b;cutoff=None
    if mode=='과거 사례 재생':
        key=f'overview-day:{a}:{b}'
        if key not in st.session_state:
            st.session_state[key]=a+(b-a)//2
        with st.sidebar:
            left,right=st.columns(2)
            if left.button('이전 1일',key=key+'prev',disabled=st.session_state[key]<=a):
                st.session_state[key]-=timedelta(days=1)
            if right.button('다음 1일',key=key+'next',disabled=st.session_state[key]>=b):
                st.session_state[key]+=timedelta(days=1)
            day=st.date_input('전체 호기 재생 기준 생산일',min_value=a,max_value=b,key=key)
        cutoff=end_of_production_day(day)
    table=analyze(a,day,cutoff)
    st.title('전체 호기 설비 이상 분석'+(' · 과거 사례 재생' if cutoff is not None else ''))
    st.caption(f'분석 기간 {a} ~ {day} · MES 생산일 기준 · 가동 = RPM {RUN_RPM} 이상, 운전 기록 1건 = 1분')
    if cutoff is not None:
        st.info(f'운전 기록 마감 {cutoff}. 생산실적은 입력 시각도 마감 이전으로 제한합니다. 불량은 발생일 기준이며 당시 등록·수정 이력은 복원하지 않습니다. 제품별 예측·실측 비교는 개별 호기를 선택하세요.')
    columns=st.columns(5)
    totals=[('전체 호기',len(table)),('운전 기록 있는 호기',int((table['기록수']>0).sum())),
            ('총 생산량(t)',round(table['kg'].sum()/1000,3) if table['kg'].notna().any() else None),('총 가동시간(h)',round(table['가동시간_h'].sum(),2) if table['기록수'].sum()>0 else None),('공정불량 기록',int(table['불량기록'].sum()))]
    for box,(label,value) in zip(columns,totals):
        box.metric(label,TD.number(value))
    st.subheader('호기별 데이터 품질 요약')
    quality=table[['line','기록수','최종기록','시각누락','주요값누락기록','기록공백','부족교대']].rename(columns={'line':'호기'})
    TD.show(quality,hide_index=True,width='stretch')
    st.caption('최종기록은 원본 운전 기록의 날짜·시각이며 초·밀리초까지 표시합니다. 가동시간_h·정지시간_h는 시간(h) 단위로, 0.5h는 30분입니다.')
    st.caption('주요값 누락은 RPM·전류·진공·Melt 온도 중 하나라도 NULL·비유한 값인 기록입니다. 공백은 10분 이상, 부족 교대는 생산이 있으나 기록 360건 미만인 교대입니다. 짧은 생산·제품 전환도 확인해야 합니다.')
    st.subheader('전체 호기 효율·이상 기록 비교')
    display=table[['line','생산량_t','가동시간_h','가동률_%','kg_h','정지횟수','정지시간_h','불량기록','불량수량_kg','확인사항']].rename(columns={'line':'호기'})
    TD.show(display,hide_index=True,width='stretch')
    if table['기록수'].sum()>0:
        st.altair_chart(alt.Chart(table[table['가동시간_h']>0]).mark_bar(color='#60a5fa').encode(
            x=alt.X('line:N',title='호기',sort='-y'),y=alt.Y('kg_h:Q',title='kg/h'),tooltip=[alt.Tooltip('line:N', title='호기')] + [alt.Tooltip(c + ':Q', format=',.2~f') for c in ['생산량_t','가동시간_h','가동률_%','kg_h']]),width='stretch')
    else:
        st.info('선택 기간에 운전 기록이 없습니다. 기간을 변경하거나 생산실적·수집 상태를 확인하세요.')
    st.caption('가동률의 분모는 호기별 달력시간입니다. Grade 구성·호기 용량이 달라 효율 순위만으로 이상을 판정하지 않습니다.')
    st.write('왼쪽에서 개별 호기를 고르면 판정 근거·정비 이력·배럴·전력·예측·모의 알림을 상세 조회할 수 있습니다.')
    from aistream_panel import render as render_pattern
    from aistream_analysis import Selection, export_parts
    pattern = render_pattern(Selection.period(a, day, cutoff=cutoff))
    pattern_meta, pattern_tables, pattern_paragraphs = export_parts(pattern)
    from agent_panel import render as render_agent
    ai_result = render_agent({'overview': table, '기간': (a,day), 'AIStream': pattern}, 'overview')
    precautions='기록 공백·누락과 불량·반복 정지 기록이 함께 있는 호기부터 원천 기록과 조치 완료 여부를 확인하세요. 효율 순위만으로 설비 이상이나 원인을 단정하지 마세요. 데이터가 없거나 허용기준이 없는 항목은 확인을 보류합니다.'
    render_download(f'전체호기_설비분석_{a}_{day}',{'모드':mode,'분석 기간':(a,day),'대상':'전체 호기','재생 마감시각':cutoff, 'AgentStream 완료':ai_result['완료'], 'AgentStream 방식':ai_result['방식'], 'AgentStream 문서근거':ai_result.get('문서근거'), 'AgentStream 오류':ai_result.get('오류'), **pattern_meta},
        {'데이터 품질 요약':quality,'호기별 효율·이상 기록':display, **pattern_tables},
        {**pattern_paragraphs, 'AgentStream 설명 ('+ai_result['방식']+')':ai_result['답변'], '권장 조치':'개별 호기를 선택해 같은 Grade 비교 및 정지·정비·불량 기록을 대조하세요.','종합 주의사항':precautions},f'overview:{mode}:{a}:{day}')
    st.subheader('종합 주의사항')
    st.write(precautions)
