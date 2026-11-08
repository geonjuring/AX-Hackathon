"""
설비 이상 분석 — 호기 + 기간 (숫자는 여기서만 계산, AI는 설명만, 판정 ≠ 원인)
기준: 「2026년 8월 호기별 설비 효율」 리포트와 같은 정의
  가동 = 메인모터 RPM 250 이상(Q5) · 운전 기록 1건 = 1분(Q12) · 가동률 분모 = 달력시간(Q11)
  기록 부족 교대 = 생산 있는데 운전 기록 360건 미만(Q13) · 생산일 = MES 생산일(p_date)
"""
from datetime import date, timedelta

import pandas as pd

from slp.analysis.lot_analysis import BARREL_TOL, RUN_RPM, q

STOP_MIN = 10        # 정지 구간으로 볼 최소 길이(분)
GAP_MIN = 10         # 운전 기록이 이만큼 끊기면 '기록 공백'
SHIFT_MIN_REC = 360  # Q13


def ds(d):  # date → 'YYYY.MM.DD'
    return d.strftime("%Y.%m.%d")


def lines():
    return q("SELECT DISTINCT line FROM lot_run WHERE line IS NOT NULL ORDER BY line")["line"].tolist()


def has_power():
    return not q("SELECT 1 FROM information_schema.tables WHERE table_name='power'").empty


# ---------------- 효율 (설비 효율 리포트와 같은 계산) ----------------
def efficiency(a, b):
    days = (b - a).days + 1
    run = q(f"SELECT line, count(*) FILTER (WHERE mval02>={RUN_RPM}) n_run FROM feeder "
            f"WHERE p_date BETWEEN ? AND ? GROUP BY line", [ds(a), ds(b)])
    prod = q("SELECT line, sum(pr_qty) kg FROM result WHERE p_date BETWEEN ? AND ? GROUP BY line", [ds(a), ds(b)])
    d = prod.merge(run, on="line", how="outer").fillna(0)
    d["가동시간_h"] = d["n_run"] / 60
    d["가동률_%"] = (d["가동시간_h"] / (days * 24) * 100).round(1)
    d["kg_h"] = (d["kg"] / d["가동시간_h"]).where(d["가동시간_h"] > 0).round(1)
    d["생산량_t"] = (d["kg"] / 1000).round(1)
    return d.sort_values("kg_h", ascending=False)[["line", "생산량_t", "가동시간_h", "가동률_%", "kg_h"]]


def short_shifts(line, a, b):
    f = q(f"""SELECT p_date, CASE WHEN strftime(ts,'%H%M') >= '0830' AND strftime(ts,'%H%M') < '2030' THEN '1' ELSE '2' END juya,
              count(*) n FROM feeder WHERE line=? AND p_date BETWEEN ? AND ? GROUP BY ALL""", [line, ds(a), ds(b)])
    p = q("SELECT p_date, juya, sum(pr_qty) kg FROM result WHERE line=? AND p_date BETWEEN ? AND ? GROUP BY ALL HAVING sum(pr_qty)>0",
          [line, ds(a), ds(b)])
    d = p.merge(f, on=["p_date", "juya"], how="left").fillna({"n": 0})
    d = d[d["n"] < SHIFT_MIN_REC]
    d["교대"] = d["juya"].map({"1": "주간", "2": "야간"})
    return d.sort_values("p_date")[["p_date", "교대", "n", "kg"]].rename(columns={"n": "운전기록(건)", "kg": "생산량(kg)"})


# ---------------- 정지 구간 · 기록 공백 ----------------
def stops(line, a, b):
    f = q(f"SELECT ts, p_date, lot_no, mval02, stop_cd FROM feeder WHERE line=? AND p_date BETWEEN ? AND ? "
          f"AND ts IS NOT NULL ORDER BY ts", [line, ds(a), ds(b)])
    if f.empty:
        return pd.DataFrame(), pd.DataFrame()
    f["run"] = f["mval02"].fillna(0) >= RUN_RPM
    f["gap"] = f["ts"].diff().dt.total_seconds().div(60).fillna(1)
    f["seg"] = (f["run"] != f["run"].shift()).cumsum()
    st = f[~f["run"]].groupby("seg").agg(시작=("ts", "min"), 종료=("ts", "max"), 생산일=("p_date", "first"),
                                         LOT=("lot_no", "first"), 기록수=("ts", "size"),
                                         비가동코드=("stop_cd", lambda s: ",".join(sorted({x for x in s.dropna() if str(x).strip()})) or "-"))
    st["분"] = ((st["종료"] - st["시작"]).dt.total_seconds() / 60 + 1).round(0)
    st = st[st["분"] >= STOP_MIN].sort_values("시작").reset_index(drop=True)
    g = f[f["gap"] >= GAP_MIN]
    gaps = pd.DataFrame({"공백 시작": f["ts"].shift()[g.index], "공백 끝": g["ts"], "분": g["gap"].round(0)}).reset_index(drop=True)
    return st, gaps


def notes(line, a, b):
    n = int(line)
    d = q("SELECT p_date, juya, prod_desc1, prod_desc2, notwk_time FROM rpt_dtl WHERE line=? AND p_date BETWEEN ? AND ?",
          [line, ds(a), ds(b)])
    d1 = d.melt(id_vars=["p_date", "juya", "notwk_time"], value_vars=["prod_desc1", "prod_desc2"], value_name="내용").dropna(subset=["내용"])
    d1 = d1[~d1["내용"].str.strip().isin(["", "***"])]
    d1["출처"] = "호기별 일보"
    r = q("SELECT p_date, juya, facil_desc1, facil_desc2, spe_desc1, spe_desc2 FROM rpt WHERE p_date BETWEEN ? AND ?", [ds(a), ds(b)])
    r = r.melt(id_vars=["p_date", "juya"], value_name="내용").dropna(subset=["내용"])
    r = r[r["내용"].str.contains(rf"(?<!\d){n}\s*호기")]
    r["출처"] = "생산일보 설비·특이사항"
    out = pd.concat([d1[["p_date", "juya", "출처", "내용"]], r[["p_date", "juya", "출처", "내용"]]])
    out["교대"] = out["juya"].map({"1": "주간", "2": "야간"})
    out["구분"] = out["내용"].str.strip().str.match(r"(?i)^G\s*/?\s*C").map({True: "Grade 교체", False: "설비·작업"})
    notwk = d["notwk_time"].fillna(0).sum()
    return out.sort_values("p_date")[["p_date", "교대", "구분", "출처", "내용"]].drop_duplicates(), notwk


# ---------------- 운전값 ----------------
def weekly(line, a, b):
    return q(f"""SELECT date_trunc('week', ts)::DATE 주, count(*) n_run,
        quantile_cont(mval02,0.5) "메인모터 RPM", quantile_cont(mval03,0.5) 전류, quantile_cont(mval01,0.5) 진공,
        quantile_cont(cval08,0.5) "Melt 온도",
        quantile_cont(mval03/NULLIF(mval02,0),0.5) "전류/RPM"
        FROM feeder WHERE line=? AND p_date BETWEEN ? AND ? AND mval02>={RUN_RPM} GROUP BY 1 ORDER BY 1""", [line, ds(a), ds(b)])


def by_grade(line, a, b, ba, bb):
    sql = f"""SELECT p.grade, count(*) n, quantile_cont(f.mval02,0.5) rpm, quantile_cont(f.mval03,0.5) amp,
              quantile_cont(f.mval01,0.5) vac FROM feeder f JOIN plan p USING (lot_no)
              WHERE f.line=? AND f.p_date BETWEEN ? AND ? AND f.mval02>={RUN_RPM} GROUP BY 1"""
    cur = q(sql, [line, ds(a), ds(b)])
    base = q(sql, [line, ds(ba), ds(bb)])
    d = cur.merge(base, on="grade", how="left", suffixes=("", "_기준")).sort_values("n", ascending=False).head(8)
    for c, nm in [("rpm", "RPM"), ("amp", "전류"), ("vac", "진공")]:
        d[f"{nm} 변화%"] = ((d[c] - d[f"{c}_기준"]) / d[f"{c}_기준"].abs() * 100).round(1)
    return d.rename(columns={"n": "가동기록", "rpm": "RPM", "amp": "전류", "vac": "진공", "rpm_기준": "RPM_기준",
                             "amp_기준": "전류_기준", "vac_기준": "진공_기준", "n_기준": "가동기록_기준"})


def barrel(line, a, b):
    sel = ", ".join(f"quantile_cont(gval{i:02d},0.5) s{i}, quantile_cont(bval{i:02d},0.5) v{i}, "
                    f"count(*) FILTER (WHERE gval{i:02d}>0 AND abs(bval{i:02d}-gval{i:02d})>{BARREL_TOL}) e{i}" for i in range(1, 11))
    d = q(f"SELECT count(*) n, {sel} FROM feeder WHERE line=? AND p_date BETWEEN ? AND ? AND mval02>={RUN_RPM}", [line, ds(a), ds(b)])
    x = d.iloc[0]
    return pd.DataFrame([{"배럴": f"{i}존", "설정": x[f"s{i}"], "실측": x[f"v{i}"],
                          "초과%": round(x[f"e{i}"] / x["n"] * 100, 1) if x["n"] else None} for i in range(1, 11)])


def power(line, a, b):
    if not has_power():
        return pd.DataFrame(), pd.DataFrame()
    e = b + timedelta(days=1)
    tot = q("SELECT 구분, any_value(센서명) 센서, sum(kwh) kWh, avg(kw) 평균_kW, quantile_cont(kw,0.95) p95_kW, count(*) n "
            "FROM power WHERE line=? AND ts>=? AND ts<? GROUP BY 1", [line, a, e])
    wk = q("SELECT date_trunc('week', ts)::DATE 주, 구분, sum(kwh) kWh, avg(kw) 평균_kW FROM power "
           "WHERE line=? AND ts>=? AND ts<? GROUP BY ALL ORDER BY 1", [line, a, e])
    return tot, wk


def defects_in(line, a, b):
    return q("SELECT q_date 발생일자, lot_no LOT, bad_nm 유형, bad_qty \"수량(kg)\" FROM quality WHERE line=? AND q_date BETWEEN ? AND ? ORDER BY 1",
             [line, ds(a), ds(b)])


# ---------------- 전체 ----------------
def analyze(line, a, b):
    days = (b - a).days + 1
    bb = a - timedelta(days=1)
    ba = bb - timedelta(days=days - 1)
    ba = max(ba, date(2026, 1, 1))
    eff, effb = efficiency(a, b), efficiency(ba, bb)
    me = eff[eff["line"] == line]
    mb = effb[effb["line"] == line]
    if me.empty or me["가동시간_h"].iloc[0] == 0:
        return {"오류": f"{line}호기 {a} ~ {b} 운전 기록이 없습니다."}
    me, mb = me.iloc[0], (mb.iloc[0] if len(mb) else None)
    ev = eff[eff["가동시간_h"] > 0]
    allavg_u = ev["가동시간_h"].sum() / (days * 24 * len(ev)) * 100
    allavg_k = ev["생산량_t"].sum() * 1000 / ev["가동시간_h"].sum()
    st, gaps = stops(line, a, b)
    sh = short_shifts(line, a, b)
    nt, notwk = notes(line, a, b)
    wk = weekly(line, a, b)
    gr = by_grade(line, a, b, ba, bb)
    br, brb = barrel(line, a, b), barrel(line, ba, bb)
    br["기준기간 초과%"] = brb["초과%"]
    pw, pwk = power(line, a, b)
    pwb, _ = power(line, ba, bb)
    dfc = defects_in(line, a, b)
    rank = int((eff["kg_h"] > me["kg_h"]).sum()) + 1

    J = []
    bl = lambda v, f: "-" if v is None or pd.isna(v) else f.format(v)
    J.append(["가동률", "기준 미정", f"{me['가동률_%']}% · 기준기간 {bl(mb['가동률_%'] if mb is not None else None, '{}%')} · 같은 기간 전체 호기 평균 {allavg_u:.1f}%",
              "가동 = 메인모터 RPM 250 이상(Q5), 분모 = 달력시간(Q11)"])
    gc = nt[nt["구분"] == "Grade 교체"]["내용"].str.extract(r"(\d+)")[0].astype(float).fillna(1).sum() if len(nt) else 0
    J.append(["시간당 생산량(kg/h)", "기준 미정", f"{me['kg_h']:,} · {rank}/{len(ev)}위 · 기준기간 {bl(mb['kg_h'] if mb is not None else None, '{:,}')} · 전체 평균 {allavg_k:,.1f} · Grade 교체 {gc:.0f}회",
              "생산 Grade 구성에 따라 달라짐 — 아래 같은 Grade 비교 참고"])
    J.append([f"정지 구간({STOP_MIN}분 이상)", "있음" if len(st) else "없음",
              f"{len(st)}회 · 합계 {st['분'].sum() / 60:,.1f}h · 최장 {st['분'].max():,.0f}분 ({st.loc[st['분'].idxmax(), '시작']:%m-%d %H:%M})" if len(st) else "-",
              f"메인모터 RPM 250 미만 연속 기록 · 생산일보 비가동시간 합 {notwk:,.0f}"])
    J.append(["운전 기록 공백·부족 교대", "있음" if len(gaps) or len(sh) else "없음",
              f"공백 {len(gaps)}회 · 기록 부족 교대 {len(sh)}개" + (f" ({', '.join(sh['p_date'].str[5:] + ' ' + sh['교대'])})" if len(sh) and len(sh) <= 4 else ""),
              "설비 정지가 아닌 데이터 수집 문제일 수 있음(Q13)"])
    ntf = nt[nt["구분"] == "설비·작업"] if len(nt) else nt
    J.append(["설비 정비·특이사항 기록", "있음" if len(ntf) else "없음", f"{len(ntf)}건" + (f" · 예: {ntf['내용'].iloc[0][:30]}" if len(ntf) else ""),
              "호기별 생산일보 + 생산일보 설비 특이사항(‘N호기’ 언급)"])
    g = gr.dropna(subset=["전류 변화%"]) if len(gr) else gr
    if len(g):
        x = g.iloc[0]
        J.append(["같은 Grade 운전값 변화", "기준 미정",
                  f"{x['grade']}: 전류 {x['전류 변화%']:+.1f}% · RPM {x['RPM 변화%']:+.1f}% · 진공 {x['진공 변화%']:+.1f}% (기준기간 대비 가운데 값)",
                  "제품 요인을 빼려고 같은 Grade끼리 비교 · 판정 기준 없음(Q15)"])
    else:
        J.append(["같은 Grade 운전값 변화", "데이터 없음", "기준기간에 같은 Grade 생산 없음", "-"])
    k = br["초과%"].idxmax()
    J.append([f"배럴 온도 ±{BARREL_TOL}℃ 초과", "기준 미정",
              f"최대 {br.loc[k, '배럴']} {br.loc[k, '초과%']}% (기준기간 {br.loc[k, '기준기간 초과%']}%) · 실측 {br.loc[k, '실측']:.0f}℃ / 설정 {br.loc[k, '설정']:.0f}℃",
              "MES 코드 U400 · 정상 운전에서도 흔함(Q15)"])
    if len(pw):
        t = []
        for kind in ("모터", "히터"):
            r = pw[pw["구분"] == kind]
            rb = pwb[pwb["구분"] == kind] if len(pwb) else pwb
            if len(r) and me["생산량_t"]:
                u = r["kWh"].iloc[0] / me["생산량_t"]
                ub = (rb["kWh"].iloc[0] / mb["생산량_t"]) if len(rb) and mb is not None and mb["생산량_t"] else None
                t.append(f"{kind} {u:,.0f} kWh/t" + (f" (기준기간 {ub:,.0f}, {((u - ub) / ub * 100):+.1f}%)" if ub else ""))
        J.append(["전력 원단위 (EX 모터·히터)", "기준 미정", " · ".join(t) or "-", "EMS 15분 집계 · 센서 이름으로 호기 연결"])
    else:
        J.append(["전력 원단위 (EX 모터·히터)", "데이터 없음", "-", "이 호기 전력 센서 없음 또는 scripts.prepare.prep_equip 미실행"])
    J.append(["이 호기 공정불량", "있음" if len(dfc) else "없음",
              f"{len(dfc)}건 · {dfc['수량(kg)'].sum():,.0f} kg" if len(dfc) else "-", "MES 공정불량 대장"])
    return {"line": line, "기간": (a, b), "기준기간": (ba, bb), "판정표": pd.DataFrame(J, columns=["항목", "판정", "데이터", "근거"]),
            "효율": eff, "요약": me, "정지": st, "공백": gaps, "부족교대": sh, "메모": nt, "주별": wk, "Grade": gr,
            "배럴": br, "전력": pw, "전력주별": pwk, "불량": dfc}
