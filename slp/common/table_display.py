"""Presentation-only comparisons. Reference differences never imply defects."""
import math
import re

import pandas as pd
from slp.common.number_format import number, text

LOW = 'color: #60a5fa; font-weight: bold'
HIGH = 'color: #f87171; font-weight: bold'
LEGEND = '파란색·굵게 = 비교 기준보다 낮음 / 빨간색·굵게 = 비교 기준보다 높음. 색상은 비교 방향이며 불량 확정이나 원인 판정이 아닙니다.'


def direction(value, reference, tolerance=0):
    try:
        value, reference = float(value), float(reference)
        if not math.isfinite(value) or not math.isfinite(reference):
            return ''
    except (TypeError, ValueError):
        return ''
    return LOW if value < reference - tolerance else HIGH if value > reference + tolerance else ''


def pair_styles(frame, pairs, tolerance=0):
    styles = pd.DataFrame('', index=frame.index, columns=frame.columns)
    for actual, reference in pairs:
        if actual in frame and reference in frame:
            styles[actual] = [direction(v, r, tolerance) for v, r in zip(frame[actual], frame[reference])]
    return styles


def pairs(frame, column_pairs, tolerance=0):
    return frame.style.apply(lambda _: pair_styles(frame, column_pairs, tolerance), axis=None)


def recipe(frame, index, values, actual, reference):
    table = frame.pivot_table(index=index, columns='lot_no', values=values)
    comparisons = [((actual, lot), (reference, lot)) for lot in frame['lot_no'].unique()]
    styles = pair_styles(table, comparisons)
    for col in table.columns:
        if col[0] in ('차이율', '배치최대차이율'):
            styles[col] = table[col].map(lambda x: direction(x, 0))
    return table.style.apply(lambda _: styles, axis=None)


def process(frame, lot, comparisons):
    table = frame.copy()
    cols = [f'{c} 가운데값' for c in comparisons if f'{c} 가운데값' in table]
    if cols:
        table['비교 LOT 평균(참고)'] = table[cols].mean(axis=1)
    return pairs(table, [(f'{lot} 가운데값', '비교 LOT 평균(참고)')])


_NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)'
_SPEC = re.compile(rf'^({_NUMBER})\s*\(\s*({_NUMBER})\s*~\s*({_NUMBER})\s*\)$')


def physical_style(value):
    match = _SPEC.match(str(value))
    if not match:
        return ''
    value, low, high = map(float, match.groups())
    if low > high:
        return ''
    return LOW if value < low else HIGH if value > high else ''


def physical(frame):
    cols = [c for c in ['MI (규격)', 'IZOD (규격)'] if c in frame]
    return frame.style.map(physical_style, subset=cols)


def required_standard(item):
    if '배럴' in item:
        return '호기·제품별 허용편차, 지속시간・초과율 기준（±10℃는 현재 참고 집계 기준）'
    if '처방' in item:
        return '계량·믹서의 수량 단위와 원료별 허용오차, 배치별 적용 기준'
    if '전력' in item:
        return '호기·제품별 kWh/t 목표와 허용 증가율'
    if '가동률' in item:
        return '가동률 목표와 달력시간·계획가동시간 중 적용 분모'
    if '생산량' in item:
        return '호기·Grade별 kg/h 목표와 허용 하락률'
    return '호기·Grade별 RPM·진공·전류 허용범위 또는 허용 변화율'


def judgment(frame):
    table = frame.copy()
    table['추가로 필요한 기준·자료'] = [required_standard(r['항목']) if r['판정'] == '기준 미정'
                                           else '해당 항목의 측정값·규격 보완' if r['판정'] in ('데이터 없음', '데이터 부족')
                                           else '—' for r in table.to_dict('records')]
    table['판정'] = table['판정'].replace({'기준 미정': '판정 보류 · 기준 필요', '없음': '확인된 이탈·기록 없음',
                                         '있음': '이탈·기록 있음', '데이터 없음': '확인 불가 · 데이터 없음',
                                         '데이터 부족': '확인 불가 · 데이터 부족'})
    table = table.rename(columns={'데이터': '관측·비교 결과', '근거': '판정·비교 근거'})
    colors = {'이탈·기록 있음': 'background-color: #4c1d24; color: #fecaca; font-weight: bold',
              '판정 보류 · 기준 필요': 'background-color: #422f13; color: #fde68a',
              '확인 불가 · 데이터 없음': 'color: #cbd5e1', '확인 불가 · 데이터 부족': 'color: #cbd5e1'}
    return table.style.map(lambda x: colors.get(x, ''), subset=['판정'])


def pretty(data):
    from slp.common.number_format import number, text
    from pandas.api.types import is_numeric_dtype, is_datetime64_any_dtype
    styler = data.style if isinstance(data, pd.DataFrame) else data
    formatters = {}
    for col in styler.data.columns:
        if is_datetime64_any_dtype(styler.data[col]):
            formatters[col] = lambda value: value.isoformat(sep=' ', timespec='milliseconds')
        elif is_numeric_dtype(styler.data[col]):
            formatters[col] = number
        elif col in ('데이터', '관측·비교 결과', 'MI (규격)', 'IZOD (규격)') or '5%~95%' in str(col):
            formatters[col] = text
    return styler.format(formatters, na_rep='—')


def show(data, *, container=None, **kwargs):
    import streamlit as st
    from pandas.api.types import is_datetime64_any_dtype
    frame = data if isinstance(data, pd.DataFrame) else data.data
    configs = {col: st.column_config.DatetimeColumn(format='YYYY-MM-DD HH:mm:ss.SSS')
               for col in frame.columns if is_datetime64_any_dtype(frame[col])}
    configs.update(kwargs.pop('column_config', None) or {})
    return (container or st).dataframe(pretty(data), column_config=configs, **kwargs)
