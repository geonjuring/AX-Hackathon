"""
LOT 이상 분석 — 계산 엔진 (숫자는 모두 여기서 계산, AI는 설명만)
규칙은 「LOT 64548438 이상 분석」 리포트(Q4·Q5·Q15·Q16·Q17 가정)를 그대로 따름
"""
import os
from datetime import timedelta

import duckdb
import pandas as pd

from slp.config import DB_PATH
DB = str(DB_PATH)
RUN_RPM = 250          # Q5: 메인모터 RPM 250 이상 = 가동
BARREL_TOL = 10        # MES 코드 U400 ±10℃ (판정 기준으로는 쓰지 않음, Q15)
NEAR_DAYS = 3          # 같은 호기 ±3일 주변 불량
COMPARE_DAYS = 365     # Q16: 비교 LOT 1년 이내

PROC = [("fval01", "피더1 RPM"), ("fval02", "피더2 RPM"), ("fval03", "피더3 RPM"), ("mval01", "진공"),
        ("mval02", "메인모터 RPM"), ("mval03", "전류")] + [(f"cval0{i}", n) for i, n in enumerate(
        ["Die 온도", "Tank1 온도", "Tank2 온도", "Pipe 온도", "Water bath1 온도", "Water bath2 온도", "Gear Oil 온도", "Melt 온도"], 1)]
JUDGE_PROC = [("mval02", "메인모터 RPM"), ("mval01", "진공"), ("mval03", "전류")]


def _con():
    return duckdb.connect(DB, read_only=True, config={"threads": 4, "memory_limit": "2GB"})


def q(sql, params=None):
    with _con() as c:
        return c.execute(sql, params or []).df()


def pdate(s):
    return pd.to_datetime(str(s).replace(".", "-")[:10], errors="coerce")


# ---------------- 기본 정보 ----------------
def lot_info(lot):
    p = q("SELECT * FROM plan WHERE lot_no=?", [lot])
    r = q("SELECT * FROM result WHERE lot_no=? ORDER BY input_dt", [lot])
    run = q("SELECT * FROM lot_run WHERE lot_no=?", [lot])
    if p.empty and r.empty and run.empty:
        return None
    i = {"lot": lot}
    if not p.empty:
        i.update(p.iloc[0].to_dict())
    if not r.empty:
        i["line"] = i.get("line") or r["line"].iloc[0]
        i["생산량"] = r["pr_qty"].sum()
        last = r[r["last_flag"] == "Y"]
        i["잔량"] = last["las_qty"].iloc[-1] if len(last) else None
        i["생산일_처음"], i["생산일_마지막"] = r["p_date"].min(), r["p_date"].max()
    if not run.empty:
        i.update(run.iloc[0].drop(["line"]).to_dict())
    return i


def physical(lot):
    d = q("SELECT * FROM qmat WHERE lot_no=? ORDER BY input_dt DESC LIMIT 1", [lot])
    if d.empty:
        return None
    x = d.iloc[0]
    def one(v, lo, hi):
        meas = v if pd.notna(v) and v != 0 else None
        spec = f"{lo:g}~{hi:g}" if pd.notna(lo) and pd.notna(hi) and (lo or hi) else "-~-"
        out = None if meas is None or spec == "-~-" else not (lo <= meas <= hi)
        return {"값": meas, "규격": spec, "이탈": out}
    return {"일자": x["p_date"], "주야": {"1": "주간", "2": "야간"}.get(str(x["juya"]), x["juya"]),
            "MI": one(x["set_val1"], x["min_val1"], x["max_val1"]),
            "IZOD": one(x["set_val2"], x["min_val2"], x["max_val2"]),
            "MES판정": f"{x['acc_fg1']}/{x['acc_fg2']}"}


def defects(lot):
    return q("SELECT q_date 발생일자, line 호기, lot_no LOT, bad_nm 유형, bad_qty \"수량(kg)\", act_desc 조치내용 "
             "FROM quality WHERE lot_no=? ORDER BY q_date", [lot])


def near_defects(info):
    if not info.get("p_first"):
        return pd.DataFrame()
    a = pdate(info["p_first"]) - timedelta(days=NEAR_DAYS)
    b = pdate(info["p_last"]) + timedelta(days=NEAR_DAYS)
    d = q("SELECT q_date 발생일자, line 호기, lot_no LOT, bad_nm 유형, bad_qty \"수량(kg)\", act_desc 조치내용 "
          "FROM quality WHERE line=?", [info["line"]])
    d = d[(d["발생일자"].map(pdate) >= a) & (d["발생일자"].map(pdate) <= b)]
    d.attrs["기간"] = f"{a:%Y-%m-%d} ~ {b:%Y-%m-%d}"
    return d.sort_values("발생일자")


# ---------------- 비교 LOT (Q16) ----------------
def pick_compare(info, n=2):
    c = q("""SELECT p.lot_no, max(r.p_date) last_date FROM plan p JOIN result r USING (lot_no)
             JOIN lot_run u USING (lot_no)
             WHERE p.line=? AND p.grade=? AND p.color=? AND p.lot_no<>? AND u.n_run>0
               AND p.lot_no NOT IN (SELECT lot_no FROM quality)
             GROUP BY p.lot_no""", [info["line"], info["grade"], info["color"], info["lot"]])
    first = pdate(info.get("생산일_처음") or info.get("p_first"))
    c["d"] = c["last_date"].map(pdate)
    c = c[(c["d"] <= first) & (c["d"] >= first - timedelta(days=COMPARE_DAYS))]
    return c.sort_values("d", ascending=False)["lot_no"].head(n).tolist()


# ---------------- 공정조건 ----------------
def process_stats(lots):
    cols = [c for c, _ in PROC] + [f"bval{i:02d}" for i in range(1, 11)] + [f"gval{i:02d}" for i in range(1, 11)]
    sel = ", ".join(f"quantile_cont({c}, 0.5) AS {c}_p50, quantile_cont({c}, 0.05) AS {c}_p05, "
                    f"quantile_cont({c}, 0.95) AS {c}_p95" for c in cols)
    exc = ", ".join(f"count(*) FILTER (WHERE gval{i:02d}>0 AND abs(bval{i:02d}-gval{i:02d})>{BARREL_TOL}) AS ex{i:02d}"
                    for i in range(1, 11))
    ph = ",".join("?" * len(lots))
    return q(f"SELECT lot_no, count(*) n_run, {sel}, {exc} FROM feeder WHERE lot_no IN ({ph}) AND mval02>={RUN_RPM} "
             f"GROUP BY lot_no", lots).set_index("lot_no")


def barrel_table(st, lots):
    rows = []
    for i in range(1, 11):
        r = {"배럴": f"{i}존"}
        for l in lots:
            if l not in st.index:
                continue
            s = st.loc[l]
            r[f"{l} 설정"], r[f"{l} 실측"] = s[f"gval{i:02d}_p50"], s[f"bval{i:02d}_p50"]
            r[f"{l} 초과%"] = round(s[f"ex{i:02d}"] / s["n_run"] * 100, 1) if s["n_run"] else None
            r[f"{l} 초과건"] = int(s[f"ex{i:02d}"])
        rows.append(r)
    return pd.DataFrame(rows)


def process_table(st, lots):
    rows = []
    for c, nm in PROC:
        r = {"항목": nm}
        for l in lots:
            if l in st.index:
                s = st.loc[l]
                r[f"{l} 가운데값"] = s[f"{c}_p50"]
                r[f"{l} 5%~95%"] = f"{s[f'{c}_p05']:.1f} ~ {s[f'{c}_p95']:.1f}" if pd.notna(s[f"{c}_p05"]) else "-"
        rows.append(r)
    return pd.DataFrame(rows)


# ---------------- 처방 (Q17: 단위 확인 전, 값 그대로) ----------------
def recipe_weigh(lots):
    ph = ",".join("?" * len(lots))
    d = q(f"SELECT lot_no, item_no 원료, string_agg(DISTINCT item_grade, ' / ' ORDER BY item_grade) 등급, string_agg(DISTINCT item_mode, ' / ' ORDER BY item_mode) 구분, sum(std_qty) 기준, "
          f"sum(meas_qty) 실측 FROM mmat WHERE lot_no IN ({ph}) GROUP BY ALL ORDER BY lot_no, item_no", lots)
    d["차이율"] = ((d["실측"] - d["기준"]) / d["기준"] * 100).where(d["기준"] > 0).round(2)
    d.loc[d["차이율"] == 0, "차이율"] = 0.0
    return d


def recipe_mixer(lots):
    ph = ",".join("?" * len(lots))
    m = q(f"SELECT * FROM mixer WHERE lot_no IN ({ph})", lots)
    out = []
    for lot, d in m.groupby("lot_no"):
        slots = [("1종", f"cval{i:02d}", f"sval{i:02d}", f"item{i:02d}", i) for i in range(1, 16)] + \
                [("2종", f"cval{50 + i}", f"sval{50 + i}", f"sitem{i:02d}", i) for i in range(1, 11)]
        for kind, c, s, n, k in slots:
            cv, sv = d[c].fillna(0), d[s].fillna(0)
            if cv.sum() == 0 and sv.sum() == 0:
                continue
            nm = d[n].dropna()
            nm = nm[nm != ""]
            name = nm.mode().iloc[0] if len(nm) else f"{kind} {k}번 칸"
            per = ((sv - cv) / cv * 100).where(cv > 0)
            mx = per.loc[per.abs().idxmax()] if per.notna().any() else None
            out.append({"lot_no": lot, "종": kind, "원료": name, "설정": cv.sum(), "측정": sv.sum(),
                        "차이율": round((sv.sum() - cv.sum()) / cv.sum() * 100, 2) if cv.sum() else None,
                        "배치최대차이율": round(mx, 2) if mx is not None else None, "배치수": d["bat_no"].nunique()})
    return pd.DataFrame(out)


# ---------------- 전체 분석 ----------------
def analyze(lot, n_compare=2, manual=None):
    lot = str(lot).strip()
    info = lot_info(lot)
    if info is None:
        return {"오류": f"LOT {lot} 데이터가 없습니다 (2026-01-01 ~ 2026-11-04 범위인지 확인)"}
    comps = manual or pick_compare(info, n_compare)
    lots = [lot] + comps
    st = process_stats(lots)
    infos = {l: (info if l == lot else lot_info(l)) for l in lots}
    phys = {l: physical(l) for l in lots}
    dfc, near = defects(lot), near_defects(info)
    weigh, mix = recipe_weigh(lots), recipe_mixer(lots)
    bt, pt = barrel_table(st, lots), process_table(st, lots)

    J = []
    J.append(["이 LOT 공정불량 기록", "있음" if len(dfc) else "없음",
              (f"{len(dfc)}건 · {dfc['수량(kg)'].sum():,.0f} kg (" + ", ".join(dfc['유형'].astype(str).unique()) + ")") if len(dfc) else "-",
              "MES 공정불량 대장"])
    p = phys[lot]
    if p:
        bad = [k for k in ("MI", "IZOD") if p[k]["이탈"]]
        parts = [f"{k} {p[k]['값']:.1f} (규격 {p[k]['규격']})" if p[k]["값"] is not None else f"{k} 미측정" for k in ("MI", "IZOD")]
        J.append(["물성 규격 이탈(MI·IZOD)", "있음" if bad else "없음" if all(p[k]["이탈"] is not None for k in ("MI", "IZOD")) else "데이터 부족", (" · ".join(parts) or "미측정") + f", {p['일자']}",
                  "MES 규격 상·하한 (MES 판정 표시와 다를 수 있음)"])
    else:
        J.append(["물성 규격 이탈(MI·IZOD)", "데이터 없음", "-", "MES 물성 기록 없음"])
    if lot in st.index and len(bt):
        k = bt[f"{lot} 초과%"].idxmax()
        z = bt.loc[k]
        others = "·".join(f"{bt.loc[k].get(f'{c} 초과%', '-')}%" for c in comps if f"{c} 초과%" in bt)
        J.append([f"배럴 온도 설정 ±{BARREL_TOL}℃ 초과", "기준 미정",
                  f"문제 LOT 최대 {z['배럴']} {z[f'{lot} 초과%']}% ({z[f'{lot} 초과건']:,}/{int(st.loc[lot, 'n_run']):,}건) · 같은 존 비교 LOT {others or '-'}",
                  "MES 코드 U400. 정상 LOT도 초과가 흔해 판정 기준 없음(Q15)"])
    other = near[near["LOT"] != lot] if len(near) else near
    J.append([f"같은 호기 ±{NEAR_DAYS}일 다른 LOT 불량", "있음" if len(other) else "없음",
              (f"{len(other)}건 · " + ", ".join(other["LOT"].astype(str))) if len(other) else "-",
              f"MES 공정불량 대장, {near.attrs.get('기간', '')}"])
    wm = weigh[weigh["lot_no"] == lot].dropna(subset=["차이율"])
    mm = mix[mix["lot_no"] == lot].dropna(subset=["차이율"]) if len(mix) else mix
    t = []
    if len(wm):
        w = wm.loc[wm["차이율"].abs().idxmax()]
        t.append(f"계량 최대 {w['차이율']:+.2f}% ({w['원료']})")
    if len(mm):
        w = mm.loc[mm["차이율"].abs().idxmax()]
        t.append(f"믹서 최대 {w['차이율']:+.2f}% ({w['종']} {w['원료']})" if not str(w['원료']).startswith(w['종']) else f"믹서 최대 {w['차이율']:+.2f}% ({w['원료']})")
    J.append(["처방 기준 대비 실측 차이", "기준 미정", " · ".join(t) or "-", "특이사항 판정 기준 없음(Q15) · 단위 확인 전(Q17)"])
    if lot in st.index and comps and all(c in st.index for c in comps):
        best = None
        for c, nm in JUDGE_PROC:
            a, b = st.loc[lot, f"{c}_p50"], st.loc[comps, f"{c}_p50"].mean()
            if pd.notna(a) and pd.notna(b) and b:
                r = (a - b) / abs(b) * 100
                if best is None or abs(r) > abs(best[1]):
                    best = (nm, r, a, b)
        if best:
            J.append(["RPM·진공·전류 비교 LOT 대비 차이", "기준 미정",
                      f"{best[0]} {best[1]:+.1f}% (문제 LOT {best[2]:.1f} · 비교 LOT 평균 {best[3]:.1f})",
                      "가운데 값 비교, 특이사항 판정 기준 없음(Q15)"])
    J.append(["재가공 · 물성 Hunting", "데이터 없음", "-", "MES에 원천 데이터 없음"])
    judge = pd.DataFrame(J, columns=["항목", "판정", "데이터", "근거"])

    prod = []
    for l in lots:
        i, ph_ = infos[l] or {}, phys[l] or {}
        prod.append({"구분": "문제" if l == lot else "비교", "LOT": l, "호기": i.get("line"),
                     "Grade / Color": f"{i.get('grade', '')} / {i.get('color', '')}", "계획일": i.get("prd_date"),
                     "운전 기간": f"{i.get('ts_start'):%Y-%m-%d %H:%M} ~ {i.get('ts_end'):%Y-%m-%d %H:%M}" if pd.notna(i.get("ts_start")) else "-",
                     "생산량(kg)": i.get("생산량"), "잔량(kg)": i.get("잔량"),
                     "물성 일자": f"{ph_.get('일자', '')} {ph_.get('주야', '')}".strip() or "-",
                     "MI (규격)": f"{ph_['MI']['값'] if ph_ and ph_['MI']['값'] is not None else '미측정'} ({ph_['MI']['규격']})" if ph_ else "-",
                     "IZOD (규격)": f"{ph_['IZOD']['값'] if ph_ and ph_['IZOD']['값'] is not None else '미측정'} ({ph_['IZOD']['규격']})" if ph_ else "-",
                     "MES 판정 MI/IZOD": ph_.get("MES판정", "-"),
                     "가동/전체 기록": f"{int(i.get('n_run') or 0):,} / {int(i.get('n_all') or 0):,}"})
    return {"lot": lot, "비교": comps, "info": info, "판정표": judge, "생산정보": pd.DataFrame(prod),
            "공정불량": dfc, "주변불량": near, "계량": weigh, "믹서": mix, "공정조건": pt, "배럴": bt}


def defect_lots():
    return q("SELECT lot_no, min(q_date) q_date, any_value(line) line, string_agg(DISTINCT bad_nm, ',') 유형, "
             "sum(bad_qty) qty FROM quality WHERE lot_no IN (SELECT lot_no FROM lot_run) GROUP BY lot_no ORDER BY q_date DESC")
