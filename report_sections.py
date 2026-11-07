"""Shared report ending: estimates, actions, demo alerts, final precautions."""
import streamlit as st
from forecast import analyze
import pandas as pd
import table_display as TD


@st.cache_data(show_spinner='향후 운전 추세 계산 중…')
def _forecast(kind, identity, _res):
    return analyze(_res, kind)


def render(res, kind):
    identity = (res['lot'],) if kind == 'lot' else (res['line'], *res['기간'])
    from aistream_panel import render_report
    from aistream_analysis import export_parts
    pattern = render_report(res, kind)
    res['AIStream'] = pattern
    f = _forecast(kind, identity, res)
    st.divider()
    st.subheader('향후 예측과 권장 조치')
    st.caption('같은 호기·Grade·Color의 일별 가동 중앙값 추세 · 최근 60일 중 최대 30개 관측일 · 일별 가동 기록 60건 이상, 최소 7일 필요')
    if f['보류']:
        st.info(f['보류'])
    else:
        st.write(f"분석 기준: {f['제품']} · 데이터 마감: {f['기준시각']}")
        TD.show(f['예측'], hide_index=True, width='stretch')
    st.caption('다음 3일에도 같은 제품·운전 조건이 유지되는 경우의 선형 추세 참고값입니다. 참고 범위는 회귀 잔차 ±2배이며 검증된 신뢰구간이나 고장 확률이 아닙니다. 생산계획·정비·조건 변경은 반영되지 않습니다. 분석 마감 이후의 실측값은 예측에 사용하지 않습니다.')
    actions = []
    for row in res['판정표'].to_dict('records'):
        if row['판정'] != '있음':
            continue
        name = row['항목']
        if '불량' in name or '물성' in name:
            action = '다음 동일 제품 생산 전 품질 담당자와 발생 유형·물성 재검 결과를 확인하고 검사 강화 여부를 결정하세요.'
        elif '공백' in name or '부족' in name:
            action = '예측 활용 전 수집 장치와 누락 교대 기록을 대조하고 실제 정지와 수집 장애를 구분하세요.'
        elif '정지' in name:
            action = '다음 가동 전 정지 코드·계획 정지·재가동 점검 기록을 대조하고 반복 구간을 점검하세요.'
        else:
            action = '다음 가동 전 정비 이력과 조치 완료 여부를 확인하고 잔여 작업을 정리하세요.'
        actions.append((name, row['데이터'], action))
    for name, evidence, action in actions:
        st.markdown(f'**{name}** — {TD.text(evidence)}')
        st.write(action)
        risk = ('동일 유형의 품질 문제 재발 가능성을 확인해야 합니다.' if '불량' in name or '물성' in name else '기록 누락이 반복되면 이상 감지와 예측이 지연될 수 있습니다.' if '공백' in name or '부족' in name else '미완료 조치나 반복 정지가 다음 생산의 가동·납기에 영향을 줄 수 있습니다.')
        st.caption('다음 생산에서 주의할 가능성: ' + risk + ' 발생 확률은 산정하지 않았습니다.')
    if not f['예측'].empty:
        latest = f['예측'].sort_values('예측일').groupby('항목').tail(1)
        for row in latest.to_dict('records'):
            st.write(f"{row['항목']}: 최근 실측 {TD.number(row['최근 실측'])} → {row['예측일']} 참고값 {TD.number(row['참고 예측값'])}. 동일 조건이 유지되면 {'상승' if row['일별 변화'] > 0 else '하락' if row['일별 변화'] < 0 else '유지'} 추세이므로 다음 생산 시작 시 재측정해 추세 지속 여부를 확인하세요.")
        st.write('다음 생산 시 전류·진공·RPM·Melt 온도를 재측정하고 참고 범위를 벗어나면 같은 제품의 설정값·부하·정비 상태를 대조하세요. 전류 상승과 RPM 변화가 함께 나타나면 운전 조건 변화부터 확인하세요.')
    if not actions:
        st.write('다음 생산 시작 시 물성 검사와 운전값 기록을 재확인하세요. 현재 확인된 이상 기록이 없더라도 누락 데이터와 미정 기준을 먼저 보완하세요.')
    from agent_panel import render as render_agent
    ai_result = render_agent(res, kind, f)
    from demo_alarm import render_alarm
    render_alarm(f, f'{kind}:{identity}')
    from report_export import render_download
    quality = res.get('데이터품질', {})
    tables = {}
    if quality:
        tables.update({'데이터 품질 요약': pd.DataFrame([quality['요약']]), '수치 누락 상세': quality['누락'], '기록 부족 교대': quality['교대']})
    tables.update({name: data for name, data in res.items() if isinstance(data, pd.DataFrame)})
    if isinstance(res.get('요약'), pd.Series):
        tables['설비 요약'] = pd.DataFrame([res['요약']])
    tables['예측 결과'] = f['예측']
    tables['예측 입력 이력'] = f.get('이력', pd.DataFrame())
    context = f'{kind}:{identity}'
    paragraphs = {'권장 조치': '\n'.join(f'{name}: {TD.text(evidence)} — {action}' for name, evidence, action in actions) or '다음 생산 시작 시 물성·운전값·기록 완전성을 재확인하세요.',
        '예측 해석': '다음 3일에도 동일 제품·조건이 유지될 때의 선형 추세 참고값입니다. 참고범위는 회귀 잔차 ±2배이며 검증된 신뢰구간이나 고장확률이 아닙니다.',
        '종합 주의사항': ('우선 확인할 항목: ' + ' / '.join(a[0] for a in actions) + '. ' if actions else '') + '다음 생산 전 조치 완료와 재검 결과를 확인하세요. 기준 미정은 이상 확정이 아니며 원인 판단은 담당자가 현장 결과와 함께 검토해야 합니다.'}
    if ai_result.get('답변'):
        paragraphs = {'AgentStream 설명 (' + ai_result['방식'] + ')': ai_result['답변'], **paragraphs}
    if res.get('화면 요약'):
        paragraphs = {'화면 요약': res['화면 요약'], **paragraphs}
    title = f"LOT_{res['lot']}_이상분석" if kind == 'lot' else f"{res['line']}호기_{res['기간'][0]}_{res['기간'][1]}_설비분석"
    metadata = {'모드': '이력 분석', '분석 대상': str(identity), 'LOT': res.get('lot'), '화면 질문': res.get('분석 질문'), '데이터 범위': quality.get('요약', {}).get('범위'), '비교 LOT': res.get('비교'), '기준기간': res.get('기준기간'),
                '예측 기준시각': f.get('기준시각'), '예측 제품조건': f.get('제품'), '예측 버전': 'daily-linear-v1', '예측 보류 이유': f['보류'], 'AgentStream 완료': ai_result['완료'], 'AgentStream 방식': ai_result['방식'], 'AgentStream 문서근거': ai_result.get('문서근거'), 'AgentStream 오류': ai_result.get('오류')}
    pattern_meta, pattern_tables, pattern_paragraphs = export_parts(pattern)
    metadata.update(pattern_meta)
    tables.update(pattern_tables)
    paragraphs = {**pattern_paragraphs, **paragraphs}
    render_download(title, metadata, tables, paragraphs, context, st.session_state.get('demo_alarm:' + context))
    st.subheader('종합 주의사항')
    if actions:
        st.warning('우선 확인할 항목: ' + ' / '.join(x[0] for x in actions) + '. 다음 생산 전 조치 완료와 재검 결과를 확인하고, 반복 이상이 있으면 품질·설비 담당자와 추가 점검 및 생산 진행 여부를 검토하세요.')
    else:
        st.info('다음 생산 전 검사 결과와 기록 완전성을 확인하세요. 이상 기록이 없다는 사실만으로 정상 운전이나 품질을 보장할 수는 없습니다.')
    st.write('온도·처방·운전값의 「기준 미정」은 이상 확정이 아닙니다. 예측 변화만으로 원인이나 고장을 단정하지 말고, 담당자가 승인된 작업 기준과 현장 재측정 결과를 함께 확인하세요.')
    if f['보류']:
        st.write('예측 보류 상태에서는 동일 제품의 운전 이력을 추가 확보한 뒤 다시 분석하세요.')
