"""SLP LOT 이상 분석 — Streamlit 시연 앱"""
import os

import altair as alt
import pandas as pd
import streamlit as st

import lot_analysis as LA
import table_display as TD


if not os.path.exists(LA.DB):
    st.error("slp.duckdb 가 없습니다. 먼저 `python3 prep.py` 를 실행하세요.")
    st.stop()


@st.cache_data(show_spinner=False)
def defect_list():
    return LA.defect_lots()


@st.cache_data(show_spinner="분석 중…")
def run(lot, n, manual):
    return LA.analyze(lot, n, list(manual) if manual else None)


def lot_page(mode="이력 분석"):
    with st.sidebar:
        dl = defect_list()
        opts = ["직접 입력"] + [f"{r.lot_no} · {r.q_date} · {r.line}호기 · {r.유형}" for r in dl.itertuples()]
        pick = st.selectbox("2026 공정불량 LOT", opts, index=1 if len(opts) > 1 else 0)
        lot = st.text_input("LOT 번호", value="" if pick == "직접 입력" else pick.split(" · ")[0])
        n = st.number_input("비교 LOT 수 (자동 선택)", 1, 5, 2)
        manual = st.text_input("비교 LOT 직접 지정 (쉼표로 구분, 비우면 자동)")
        go = st.button("분석", type="primary", width="stretch")
        st.caption("기간 2026-01-01 ~ 2026-11-04 · 분석용 개인정보 정제본")

    if not lot:
        st.info("왼쪽에서 LOT를 고르고 **분석**을 누르세요.")
        return

    if mode == "과거 사례 재생":
        from replay import render as render_replay
        meta = LA.q("SELECT line FROM plan WHERE lot_no=? LIMIT 1", [lot.strip()])
        if meta.empty:
            st.error("LOT의 호기·제품 정보가 없습니다.")
            return
        first = LA.q("SELECT min(p_date) d FROM feeder WHERE lot_no=?", [lot.strip()]).iloc[0]['d']
        if first is None:
            st.info("재생할 LOT 운전 기록이 없습니다.")
            return
        st.sidebar.caption("공정불량 사례 목록은 사후 선정 목록이며 예측 입력에는 사용하지 않습니다.")
        render_replay("lot", lot.strip(), meta.iloc[0]['line'], (LA.pdate(first) - pd.Timedelta(days=1)).date())
        return

    man = tuple(x.strip() for x in manual.split(",") if x.strip()) or None
    res = run(lot.strip(), int(n), man)
    if "오류" in res:
        st.error(res["오류"])
        return

    i = res["info"]
    st.title(f"LOT {res['lot']} 이상 분석")
    c = st.columns(4)
    c[0].metric("호기", i.get("line", "-"))
    c[1].metric("Grade / Color", f"{i.get('grade', '-')} / {i.get('color', '-')}")
    c[2].metric("생산량(kg)", TD.number(i.get('생산량')))
    c[3].metric("비교 LOT", ", ".join(res["비교"]) or "없음")
    st.caption("비교 LOT 자동 선택: 같은 호기·Grade·Color, 문제 LOT 첫 생산일까지 생산 완료, 공정불량 기록 없음, "
               "가동 기록(메인모터 RPM 250 이상) 있음, 1년 이내 — 최근 순")

    from data_quality import snapshot, scope, render_quality
    quality = snapshot(**scope(res, "lot"))
    res['데이터품질'] = quality
    render_quality(quality, res['판정표'], len(res['비교']))

    st.subheader("판정 (문제 LOT 기준)")
    TD.show(TD.judgment(res["판정표"]), hide_index=True, width="stretch")
    st.caption("판정은 데이터 대조 결과이며 **원인 판단이 아닙니다.** 결론은 담당자가 작성합니다. "
               "「판정 보류 · 기준 필요」는 비교 결과는 있지만 정상·이상 판정에 필요한 현장 기준이 없는 항목입니다. 기록이 없거나 기준을 벗어나지 않았다는 사실만으로 정상임을 보장하지 않습니다.")

    st.caption(TD.LEGEND)
    t = st.tabs(["생산정보·물성", "공정불량", "처방", "공정조건", "배럴 온도"])
    with t[0]:
        st.caption("물성은 규격 하한 미만이면 파란색·굵게, 상한 초과이면 빨간색·굵게 표시합니다. 미측정·규격 없음은 색칠하지 않습니다.")
        TD.show(TD.physical(res["생산정보"]), hide_index=True, width="stretch")
    with t[1]:
        st.markdown("**이 LOT 공정불량**")
        TD.show(res["공정불량"], hide_index=True, width="stretch")
        st.markdown(f"**같은 호기 주변 공정불량** ({res['주변불량'].attrs.get('기간', '')})")
        TD.show(res["주변불량"], hide_index=True, width="stretch")
    with t[2]:
        st.markdown("**원료 계량 (기준 · 실측 · 차이율%)** — MES 값 그대로, 단위 확인 전(Q17)")
        w = res["계량"]
        if len(w):
            TD.show(TD.recipe(w, ["원료", "등급", "구분"], ["기준", "실측", "차이율"], "실측", "기준"),
                         width="stretch")
        st.markdown("**믹서 (설정 · 측정 · 차이율 / 배치 최대 차이율)**")
        m = res["믹서"]
        if len(m):
            TD.show(TD.recipe(m, ["종", "원료"], ["설정", "측정", "차이율", "배치최대차이율"], "측정", "설정"),
                         width="stretch")
    with t[3]:
        st.markdown("메인모터 250 RPM 이상 운전 기록의 **가운데 값**과 5%~95% 범위 (튀는 값 영향 줄이기)")
        st.caption("문제 LOT 가운데값을 비교 LOT 가운데값의 평균과 대조합니다. 허용규격이 아닌 과거 생산값과의 비교입니다.")
        TD.show(TD.process(res["공정조건"], res["lot"], res["비교"]), hide_index=True, width="stretch")
    with t[4]:
        b = res["배럴"]
        if len(b):
            lots = [res["lot"]] + res["비교"]
            long = pd.concat([pd.DataFrame({"배럴": b["배럴"], "LOT": f"{l}{' (문제)' if l == res['lot'] else ''}",
                                            "실측": b[f"{l} 실측"]}) for l in lots if f"{l} 실측" in b])
            sett = pd.DataFrame({"배럴": b["배럴"], "설정": b[f"{res['lot']} 설정"]})
            order = list(b["배럴"])
            ch = alt.Chart(long).mark_line(point=True).encode(x=alt.X("배럴", sort=order), y=alt.Y("실측", title="℃", scale=alt.Scale(zero=False)), color="LOT")
            ch += alt.Chart(sett).mark_line(strokeDash=[4, 4], color="gray").encode(x=alt.X("배럴", sort=order), y="설정")
            st.altair_chart(ch, width="stretch")
            TD.show(TD.pairs(b, [(f"{l} 실측", f"{l} 설정") for l in lots], tolerance=LA.BARREL_TOL), hide_index=True, width="stretch")
            st.caption("배럴 실측값은 해당 LOT 설정값 −10℃ 미만 / +10℃ 초과만 강조합니다. 이는 참고 범위와의 비교이며 불량 판정 기준은 아닙니다.")
            st.caption("초과% = |실측 − 설정| > 10℃ 기록 ÷ 가동 기록 (MES 코드 U400) — 정상 LOT도 흔해 판정하지 않음(Q15). 점선 = 문제 LOT 설정")

    from report_sections import render
    render(res, "lot")

