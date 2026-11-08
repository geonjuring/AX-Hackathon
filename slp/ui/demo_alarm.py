"""Session-local simulated escalation. Never sends messages to real people."""
import streamlit as st

PEOPLE = [
    {'이름': '가상 직원 A', '원본_직급': '미확인', '시연용_역할': '담당자'},
    {'이름': '가상 직원 B', '원본_직급': '미확인', '시연용_역할': '반장'},
    {'이름': '가상 직원 C', '원본_직급': '미확인', '시연용_역할': '관리자'},
]


def advance(state, minutes):
    state['시연분'] += minutes
    for alarm in state['알림']:
        if alarm['상태'] != '미확인':
            continue
        level = min(2, (state['시연분'] - alarm['발생분']) // alarm['대기분'])
        while alarm['단계'] < level:
            alarm['단계'] += 1
            person = PEOPLE[alarm['단계']]
            alarm['이력'].append(f"{state['시연분']}분: {person['이름']}({person['시연용_역할']}) 상위 알림")


def render_alarm(forecast, context):
    st.subheader('모의 알림 시연')
    st.info('가상 인원·역할을 사용한 모의 알림 · 실제 메시지는 발송되지 않으며 현재 세션에만 저장됩니다.')
    with st.expander('시연용 담당자 정보'):
        st.dataframe(PEOPLE, hide_index=True, width='stretch')
    key = 'demo_alarm:' + context
    if key not in st.session_state:
        st.session_state[key] = {'시연분': 0, '알림': []}
    state = st.session_state[key]
    metric = st.selectbox('모의 감시 항목', ['전류', '진공', '메인모터 RPM', 'Melt 온도'], key=key+'metric')
    direction = st.selectbox('모의 발생 조건', ['이상', '이하'], key=key+'direction')
    threshold = st.number_input('시연용 임계값 (승인된 운영 기준 아님)', value=100.0, key=key+'threshold')
    wait = st.number_input('상위 알림 대기시간 (시연 분)', min_value=1, max_value=60, value=5, key=key+'wait')
    state['설정'] = {'감시 항목': metric, '발생 조건': direction, '시연용 임계값': threshold, '상위 알림 대기분': wait}
    if st.button('예측값으로 모의 조건 평가', key=key+'evaluate'):
        pred = forecast['예측']
        if pred.empty:
            st.warning('예측 보류 상태라 조건을 평가할 수 없습니다. 가상 이상 이벤트로 흐름을 시연할 수 있습니다.')
        else:
            values = pred.loc[pred['항목'] == metric, '참고 예측값']
            matches = values >= threshold if direction == '이상' else values <= threshold
            if values.empty:
                st.warning('선택한 항목은 예측 데이터가 부족합니다.')
            elif matches.any():
                _create(state, f'{metric} 예측값이 {threshold:g} {direction} (시연 조건)', int(wait))
            else:
                st.success('설정한 모의 조건에 해당하지 않습니다.')
    if st.button('가상 이상 이벤트 발생', key=key+'trigger'):
        _create(state, f'{metric} 가상 이상 이벤트 (실측·예측 판정과 무관한 시연)', int(wait))
    if st.button('시연 시간 1분 진행', key=key+'clock'):
        advance(state, 1)
    st.caption(f"시연 경과 {state['시연분']}분 · 버튼으로 시간을 진행하면 미확인 건이 담당자 → 반장 → 관리자 순서로 전달됩니다. 확인하면 상위 알림이 중단됩니다.")
    for idx, alarm in enumerate(state['알림']):
        person = PEOPLE[alarm['단계']]
        st.markdown(f"**모의 알림 #{idx + 1} · {alarm['상태']} · {person['이름']} ({person['시연용_역할']})**")
        st.write(alarm['내용'])
        a, b = st.columns(2)
        if a.button('알림 확인', key=key+f'ack{idx}', disabled=alarm['상태'] != '미확인'):
            alarm['상태'] = '확인'
            alarm['이력'].append(f"{state['시연분']}분: {person['이름']} 확인 · 상위 알림 중단")
            st.rerun()
        if b.button('조치 완료·해제', key=key+f'resolve{idx}', disabled=alarm['상태'] == '해제'):
            alarm['상태'] = '해제'
            alarm['이력'].append(f"{state['시연분']}분: 조치 완료·해제 (시연)")
            st.rerun()
        st.text('\n'.join(alarm['이력']))


def _create(state, message, wait):
    if any(a['내용'] == message and a['상태'] != '해제' for a in state['알림']):
        return
    state['알림'].append({'내용': message, '상태': '미확인', '발생분': state['시연분'], '대기분': wait, '단계': 0,
                         '이력': [f"{state['시연분']}분: 가상 직원 A(담당자) 모의 알림"]})
