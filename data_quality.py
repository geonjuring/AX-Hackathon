"""Read-only quality statistics with explicit scope and event-time bounds."""
from datetime import timedelta
import pandas as pd
import streamlit as st
from lot_analysis import q, RUN_RPM
import table_display as TD
from number_format import number


def day_string(day):
    return pd.Timestamp(day).strftime('%Y.%m.%d')


def scope(res, kind):
    if kind == 'lot':
        i = res['info']
        return dict(line=i.get('line'), lot=res['lot'], start=i.get('p_first') or i.get('생산일_처음'),
                    end=i.get('p_last') or i.get('생산일_마지막'), cutoff=None)
    return dict(line=res['line'], lot=None, start=res['기간'][0], end=res['기간'][1], cutoff=None)


@st.cache_data(show_spinner=False)
def snapshot(line, start, end, lot=None, cutoff=None, grade=None, color=None):
    if start is None or end is None:
        return {'요약': {'상태': '분석 기간 정보 없음'}, '누락': pd.DataFrame(), '교대': pd.DataFrame()}
    args = [str(line), day_string(start), day_string(end)]
    conditions = ['f.line=?', 'f.p_date BETWEEN ? AND ?']
    if lot:
        conditions.append('f.lot_no=?'); args.append(str(lot))
    if cutoff is not None:
        conditions.append('f.ts<=?'); args.append(pd.Timestamp(cutoff))
    if grade is not None and color is not None:
        conditions.append('EXISTS (SELECT 1 FROM plan p WHERE p.lot_no=f.lot_no AND p.grade=? AND p.color=?)')
        args += [grade, color]
    where = ' AND '.join(conditions)
    fields = [('mval02','메인모터 RPM'), ('mval03','전류'), ('mval01','진공'), ('cval08','Melt 온도')]
    missing = ', '.join(f'count(*) FILTER (WHERE {c} IS NULL OR NOT isfinite({c})) missing_{c}' for c,_ in fields)
    agg = q(f'''SELECT count(*) n, count(*) FILTER (WHERE mval02>={RUN_RPM}) run,
        min(ts) first_ts, max(ts) last_ts, count(*) FILTER (WHERE ts IS NULL) invalid_ts,
        count(*) FILTER (WHERE ts IS NOT NULL) - count(DISTINCT (line,ts)) FILTER (WHERE ts IS NOT NULL) duplicates,
        {missing} FROM feeder f WHERE {where}''', args).iloc[0]
    gaps = q(f'''WITH ordered AS (SELECT ts, lag(ts) OVER (ORDER BY ts) prev FROM feeder f WHERE {where})
        SELECT count(*) n FROM ordered WHERE date_diff('second',prev,ts)>=600''', args).iloc[0]['n']
    shift = q(f'''SELECT f.p_date 생산일, CASE WHEN strftime(ts,'%H%M')>='0830' AND strftime(ts,'%H%M')<'2030'
        THEN '1' ELSE '2' END juya, count(*) 기록수 FROM feeder f WHERE {where} GROUP BY ALL''', args)
    p_args = [str(line), day_string(start), day_string(end)]
    p_where = 'line=? AND p_date BETWEEN ? AND ?'
    if lot:
        p_where += ' AND lot_no=?'; p_args.append(str(lot))
    if cutoff is not None:
        p_where += ' AND input_dt<=?'; p_args.append(pd.Timestamp(cutoff))
    if grade is not None and color is not None:
        p_where += ' AND EXISTS (SELECT 1 FROM plan p WHERE p.lot_no=result.lot_no AND p.grade=? AND p.color=?)'
        p_args += [grade,color]
    prod = q(f'SELECT p_date 생산일, juya, sum(pr_qty) kg FROM result WHERE {p_where} GROUP BY ALL HAVING sum(pr_qty)>0',p_args)
    shifts = prod.merge(shift,on=['생산일','juya'],how='left').fillna({'기록수':0})
    shifts['교대'] = shifts['juya'].map({'1':'주간','2':'야간'})
    short = shifts[shifts['기록수']<360][['생산일','교대','기록수']]
    n = int(agg['n'])
    detail = pd.DataFrame([{'항목':name, '누락·비유한값(건)':int(agg['missing_'+c]), '전체 기록(건)':n,
                            '누락률(%)':round(agg['missing_'+c]/n*100,2) if n else None} for c,name in fields])
    summary = {'대상': f'{line}호기'+(f' · LOT {lot}' if lot else ''), '범위':f'{day_string(start)} ~ {day_string(end)}',
               '전체 운전 기록':n,'가동 기록':int(agg['run']), '최초 기록':agg['first_ts'], '최종 기록':agg['last_ts'],
               '시각 누락 기록':int(agg['invalid_ts']), '동일 호기·시각 중복':int(agg['duplicates']),
               '10분 이상 기록 공백':int(gaps), '기록 부족 교대':len(short)}
    if cutoff is not None:
        summary['재생 마감시각'] = pd.Timestamp(cutoff)
    if grade is not None:
        summary['제품 조건'] = f'{grade} / {color}'
    return {'요약':summary,'누락':detail,'교대':short}


def render_quality(data, judge=None, comparison_count=None):
    st.subheader('데이터 품질 요약')
    s = data['요약']
    columns = st.columns(4)
    for box,label in zip(columns,['전체 운전 기록','시각 누락 기록','10분 이상 기록 공백','기록 부족 교대']):
        box.metric(label, number(s.get(label)))
    st.caption(f"대상: {s.get('대상','—')} · 범위: {s.get('범위','—')} · 최종 기록: {s.get('최종 기록','—')}")
    if comparison_count is not None:
        st.caption(f'비교 LOT {comparison_count}개 · 비교 LOT가 없으면 비교 기반 판단을 보류하세요.')
    if judge is not None:
        pending = judge[judge['판정'].isin(['데이터 없음','데이터 부족'])]
        if not pending.empty:
            st.warning('자료 보완 필요: ' + ' / '.join(pending['항목']))
    with st.expander('누락 항목·중복·교대 상세'):
        st.write(f"동일 호기·시각 중복: {number(s.get('동일 호기·시각 중복'))}건 · 가동 기록: {number(s.get('가동 기록'))}건")
        TD.show(data['누락'], hide_index=True, width='stretch')
        TD.show(data['교대'], hide_index=True, width='stretch')
    st.caption('누락은 NULL·비유한 수치 기준이며 0은 유지합니다. 기록 부족 교대는 생산실적이 있으나 운전 기록 360건 미만인 교대입니다. 짧은 생산·제품 전환에 의한 기록 부족도 있으므로 수집 장애로 확정하지 않습니다. 공백은 실제 정지와 다를 수 있으며 수집 완전율을 뜻하지 않습니다.')
