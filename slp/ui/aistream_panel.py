"""One inference per visitor/report, with explicit retry and visible partial coverage."""
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import json
import logging
import streamlit as st
import slp.common.table_display as TD
import slp.analysis.lot_analysis as LA
from slp.ai.aistream.client import Config, AIStreamError
from slp.ai.aistream.analysis import Selection, analyze, tables


def render(selection):
    st.divider()
    st.subheader('AIStream 설비 운전 패턴 분석')
    st.caption('배포된 모델의 실제 API 결과 · 적용 범위: 06호기 / SR-0310FMU / NP · 모델 기준 확정일: 2026-10-01')
    st.caption('선택 범위 중 적용 가능한 RPM·전류·진공·LOT·제품·측정 시각을 서버에서 AIStream으로 전송합니다. 정지·누락·중복 기록은 임의 제거하지 않고 모델의 평가 보류 규칙을 적용합니다.')
    try:
        config = Config.from_env()
    except AIStreamError as exc:
        st.warning(str(exc))
        return {'요약': asdict(selection), '완료': False, '보류': '', '오류': str(exc), '응답': []}
    fingerprint = json.dumps([asdict(selection), config.url, config.timeout, Path(LA.DB).stat().st_mtime_ns], sort_keys=True)
    key = hashlib.sha256(fingerprint.encode()).hexdigest()
    states = st.session_state.setdefault('aistream_report_results', {})
    retry = st.button('AIStream 다시 분석', key='aistream-retry-'+key)
    if retry:
        states.pop(key, None)
    if key not in states:
        if len(states) >= 12:
            states.pop(next(iter(states)))
        progress = st.empty()
        try:
            with st.spinner('AIStream 운전 패턴 분석 중…'):
                result = analyze(selection, config,
                    on_progress=lambda i, n: progress.caption(f'10분 구간을 유지한 분할 요청 {i}/{n} 처리 중…'))
        except Exception as exc:
            # An optional remote feature must not make the existing report unavailable.
            logging.getLogger(__name__).error('AIStream input preparation failed: %s', type(exc).__name__)
            result = {'요약': asdict(selection), '완료': False, '보류': '',
                '오류': 'AIStream 입력 기록을 준비하지 못했습니다. 데이터 연결 상태를 확인하세요.', '응답': []}
        progress.empty()
        result['확인시각'] = datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')
        states[key] = result
    result = states[key]
    if result.get('오류'):
        st.warning(result['오류'])
        if result.get('응답'):
            st.warning('일부 요청만 완료됐습니다. 아래 값은 응답받은 구간에 한정되며 미응답 구간을 정상으로 처리하지 않습니다.')
    if result.get('보류'):
        st.info(result['보류'])
        st.caption('모델 적용 예: 06호기 · 2026-10-01 이후 / LOT 64597658. 현재 선택 대상의 기존 분석·판정은 계속 표시됩니다.')
    if result.get('응답'):
        summary = result['요약']
        st.caption('결과 확인시각: '+result['확인시각']+' · 데이터 마감: '+selection.cutoff)
        columns = st.columns(4)
        for box, (label, name) in zip(columns, [('응답 기록', '응답기록'), ('평가 구간', '평가구간'), ('이상 후보', '이상후보'), ('평가 보류 구간', '총보류구간')]):
            box.metric(label, TD.number(summary.get(name, 0)))
        if not summary.get('평가구간'):
            st.info('응답받은 구간이 모두 평가 보류 상태입니다. 정상·이상 여부를 판단할 수 없으므로 보류 사유와 필요한 기록을 확인하세요.')
        elif summary.get('이상후보'):
            st.warning(f"응답받은 구간에서 점검 후보 {summary['이상후보']}개를 확인했습니다. 불량·고장 확정이 아닙니다.")
        else:
            st.info('응답받은 평가 가능 구간에서 이상 후보가 집계되지 않았습니다. 미평가 구간과 설비·품질의 정상 여부는 별도로 확인하세요.')
        output = tables(result)
        frame = output['AIStream 구간별 결과']
        threshold = result['응답'][0]['candidate_threshold']
        st.caption(f'이상 후보 기준: 점수 > {threshold:.6g} (보정 구간 점수의 99백분위). 후보 여부는 API의 원래 수치로 판단하며, 화면의 반올림 표시값으로 재판정하지 않습니다.')
        a, b, c = st.tabs(['이상 후보', '전체 구간·보류', '관련 운전값'])
        with a:
            candidates = frame[frame['상태'].eq('패턴 이상 후보')]
            if candidates.empty:
                st.write('집계된 이상 후보 없음')
            else:
                TD.show(candidates, hide_index=True, width='stretch')
        with b:
            TD.show(frame, hide_index=True, width='stretch')
        with c:
            TD.show(output['AIStream 관련 운전값'], hide_index=True, width='stretch')
        st.caption(f"시각을 확인할 수 있는 선택 기록 {summary['선택기록']:,}건 중 모델 적용 범위 {summary['적용범위기록']:,}건. 연결 불가·범위 밖 {summary['연결불가·범위밖기록']:,}건, 모델 기준 확정 전 {summary['기준확정전기록']:,}건은 전송하지 않았습니다. 전체 호기 조회에서도 이 모델이 평가하는 범위는 06호기의 해당 제품뿐입니다.")
    if result.get('요청크기보류'):
        st.warning('요청 크기를 초과한 10분 구간은 분할 평가하지 않고 보류했습니다.')
        TD.show(tables(result)['AIStream 요청 크기 보류'], hide_index=True, width='stretch')
    st.caption('점수가 클수록 과거 참고 패턴과 다릅니다. 점수·백분위는 고장 확률이 아니며, 이 결과는 기존 일별 선형 예측·모의 알림과 별개입니다. 전류·진공의 단위는 원천 확인 전 임의로 부여하지 않습니다.')
    return result


def render_report(res, kind):
    if kind == 'lot':
        cutoff = res.get('info', {}).get('ts_end')
        if cutoff is None or str(cutoff) == 'NaT':
            st.subheader('AIStream 설비 운전 패턴 분석')
            reason = 'LOT의 운전 종료 시각이 없어 AIStream 평가는 보류합니다.'
            st.info(reason)
            return {'요약': {'LOT': res['lot']}, '완료': False, '보류': reason, '오류': '', '응답': []}
        return render(Selection.lot_scope(res['lot'], cutoff))
    return render(Selection.period(*res['기간'], line=res['line']))
