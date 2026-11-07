"""설비 이상 분석 화면 (호기 + 기간)"""
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import equip_analysis as EA
import table_display as TD



@st.cache_data(show_spinner=False)
def _lines():
    return EA.lines()


@st.cache_data(show_spinner="설비 데이터 분석 중… (처음엔 10~30초)")
def _run(line, a, b):
    return EA.analyze(line, a, b)


def equip_page(mode="이력 분석"):
    with st.sidebar:
        ls = _lines()
        line = st.selectbox("호기", ["전체"] + ls, index=0, format_func=lambda x: "전체 호기" if x == "전체" else f"{x}호기", key="equipment_line_v2")
        rng = st.date_input("기간", (date(2026, 8, 1), date(2026, 8, 31)), min_value=date(2026, 1, 1), max_value=date(2026, 11, 4))
        st.caption("기준기간 = 바로 앞의 같은 길이 기간 (자동)")
    if not isinstance(rng, (list, tuple)) or len(rng) != 2:
        st.info("기간의 시작일과 종료일을 모두 고르세요.")
        return
    if line == "전체":
        from equipment_overview import render as render_overview
        render_overview(rng[0], rng[1], mode)
        return
    if mode == "과거 사례 재생":
        from replay import render as render_replay
        render_replay("equipment", line, line, rng[0] + (rng[1] - rng[0]) // 2)
        return
    r = _run(line, rng[0], rng[1])
    if "오류" in r:
        st.error(r["오류"])
        return
    m, (ba, bb) = r["요약"], r["기준기간"]
    st.title(f"{line}호기 설비 이상 분석")
    st.caption(f"기간 {rng[0]} ~ {rng[1]} · 기준기간 {ba} ~ {bb} · 생산일 = MES 생산일(야간조는 시작한 날)")
    c = st.columns(5)
    c[0].metric("생산량", f"{TD.number(m['생산량_t'])} t")
    c[1].metric("가동시간", f"{TD.number(m['가동시간_h'])} h")
    c[2].metric("가동률", f"{TD.number(m['가동률_%'])}%")
    c[3].metric("kg/h", TD.number(m['kg_h']))
    c[4].metric("정지(10분+)", f"{len(r['정지'])}회")

    from data_quality import snapshot, scope, render_quality
    quality = snapshot(**scope(r, "equipment"))
    r['데이터품질'] = quality
    render_quality(quality, r['판정표'])

    st.subheader("판정 (이 호기·기간 기준)")
    TD.show(TD.judgment(r["판정표"]), hide_index=True, width="stretch")
    st.caption("판정은 데이터 대조 결과이며 **원인 판단이 아닙니다.** 「판정 보류 · 기준 필요」는 비교 결과는 있지만 정상·이상 판정에 필요한 현장 기준이 없는 항목입니다. 기록이 없다는 사실만으로 정상임을 보장하지 않습니다.")

    st.caption(TD.LEGEND)
    t = st.tabs(["효율 순위", "정지·공백", "정비·특이사항", "운전값 추세", "같은 Grade 비교", "배럴 온도", "전력", "공정불량"])
    with t[0]:
        e = r["효율"].copy()
        e["선택"] = e["line"] == line
        ch = alt.Chart(e).mark_bar().encode(x=alt.X("line:N", sort="-y", title="호기"), y=alt.Y("kg_h:Q", title="kg/h"),
                                           color=alt.condition("datum.선택", alt.value("#c0392b"), alt.value("#9fb0c6")),
                                           tooltip=[alt.Tooltip('line:N', title='호기')] + [alt.Tooltip(c + ':Q', format=',.2~f') for c in ['생산량_t','가동시간_h','가동률_%','kg_h']])
        st.altair_chart(ch, width="stretch")
        TD.show(e.drop(columns="선택"), hide_index=True, width="stretch")
        st.caption("「설비 효율」 리포트와 같은 계산: 가동시간 = RPM 250 이상 기록 × 1분, 가동률 = 가동시간 ÷ (일수 × 24h), kg/h = 생산량 ÷ 가동시간")
    with t[1]:
        s = r["정지"]
        if len(s):
            tl = s.assign(구분="정지")
            ch = alt.Chart(tl).mark_bar(height=18).encode(x=alt.X("시작:T", title=""), x2="종료:T", y=alt.Y("구분:N", title=""),
                                                         tooltip=["시작", "종료", "분", "LOT", "비가동코드"])
            st.altair_chart(ch, width="stretch")
        st.markdown(f"**정지 구간** (메인모터 RPM 250 미만이 {EA.STOP_MIN}분 이상)")
        TD.show(s, hide_index=True, width="stretch")
        st.markdown(f"**운전 기록 공백** ({EA.GAP_MIN}분 이상 기록 없음) · **기록 부족 교대** (생산 있는데 기록 {EA.SHIFT_MIN_REC}건 미만)")
        cc = st.columns(2)
        TD.show(r["공백"], container=cc[0], hide_index=True, width="stretch")
        TD.show(r["부족교대"], container=cc[1], hide_index=True, width="stretch")
    with t[2]:
        TD.show(r["메모"], hide_index=True, width="stretch")
        st.caption("호기별 생산일보(prod_desc) + 생산일보 설비·특이사항 중 이 호기를 언급한 기록. 개인정보 보호를 위해 호기·작업 키워드로 요약")
    with t[3]:
        w = r["주별"]
        if len(w):
            long = w.melt(id_vars=["주", "n_run"], var_name="항목", value_name="가운데 값")
            ch = alt.Chart(long).mark_line(point=True).encode(x="주:T", y=alt.Y("가운데 값:Q", scale=alt.Scale(zero=False)), color="항목").properties(height=160)
            st.altair_chart(ch.facet(row=alt.Row("항목:N", title="")).resolve_scale(y="independent"), width="stretch")
            TD.show(w, hide_index=True, width="stretch")
        st.caption("가동 기록(RPM 250 이상)의 주별 가운데 값. 제품이 바뀌면 값도 바뀌니 「같은 Grade 비교」와 같이 보세요.")
    with t[4]:
        st.caption("운전값은 같은 Grade의 기준기간 가운데값, 변화율은 0%와 비교해 강조합니다. 비교 방향이 품질·설비 이상 판정을 뜻하지 않습니다.")
        gd = r["Grade"]
        TD.show(TD.pairs(gd, [(name, name + "_기준") for name in ["RPM", "전류", "진공"]]).map(lambda v: TD.direction(v, 0), subset=[c for c in ["RPM 변화%", "전류 변화%", "진공 변화%"] if c in gd]), hide_index=True, width="stretch")
        st.caption("같은 호기·같은 Grade끼리 기간 vs 기준기간 가운데 값 비교 — 제품 요인을 빼고 설비 변화만 보려는 표")
    with t[5]:
        b = r["배럴"]
        long = pd.concat([b[["배럴", "초과%"]].assign(기간="분석 기간"), b[["배럴", "기준기간 초과%"]].rename(columns={"기준기간 초과%": "초과%"}).assign(기간="기준기간")])
        ch = alt.Chart(long).mark_bar().encode(x=alt.X("배럴:N", sort=list(b["배럴"])), xOffset="기간:N", y="초과%:Q", color="기간:N")
        st.altair_chart(ch, width="stretch")
        TD.show(TD.pairs(b, [("실측", "설정")], tolerance=EA.BARREL_TOL), hide_index=True, width="stretch")
        st.caption("배럴 실측값은 설정값 −10℃ 미만 / +10℃ 초과만 강조합니다. 참고 범위이며 품질·설비 이상 판정 기준은 아닙니다.")
        st.caption("초과% = |실측 − 설정| > 10℃ 기록 ÷ 가동 기록 (MES 코드 U400). 히터 전력은 「전력」 탭과 같이 보세요.")
    with t[6]:
        if len(r["전력"]):
            TD.show(r["전력"], hide_index=True, width="stretch")
            ch = alt.Chart(r["전력주별"]).mark_line(point=True).encode(x="주:T", y="kWh:Q", color="구분:N")
            st.altair_chart(ch, width="stretch")
            st.caption("EMS 전력계 15분 집계 중 이 호기 EX(압출 모터)·히터 센서. 센서 이름으로 호기를 연결")
        else:
            st.info("이 호기 전력 데이터가 없습니다 (EMS 센서 없음 또는 prep_equip.py 미실행).")
    with t[7]:
        TD.show(r["불량"], hide_index=True, width="stretch")

    from report_sections import render
    render(r, "equipment")
