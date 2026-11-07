"""
LOT 이상 분석 앱 - 데이터 준비 (한 번만 실행, 서버에서 약 5~15분)
v1 CSV → lot_agent/slp.duckdb  (피더는 LOT 순으로 정렬해 저장 → 앱에서 LOT 조회가 즉시 됨)

실행:  python prep.py
"""
import os, time, duckdb

DATA = os.environ.get("SLP_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
A, R = f"{DATA}/01_분석용", f"{DATA}/02_기준정보"
DB = os.environ.get("SLP_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "slp.duckdb"))
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "duck_tmp")

def csv(p):
    return f"read_csv('{p}', all_varchar=true, header=true, sample_size=-1)"

def num(c):
    return f"TRY_CAST(NULLIF(TRIM({c}),'') AS DOUBLE) AS {c}"

FEED_NUM = ([f"fval0{i}" for i in range(1, 6)] + ["mval01", "mval02", "mval03"] +
            [f"bval{i:02d}" for i in range(1, 11)] + [f"gval{i:02d}" for i in range(1, 11)] +
            [f"cval0{i}" for i in range(1, 9)])

def main():
    t0 = time.time()
    if os.path.exists(DB):
        os.remove(DB)
    os.makedirs(TMP, exist_ok=True)
    con = duckdb.connect(DB)
    con.execute(f"SET memory_limit='1500MB'; SET threads=2; SET temp_directory='{TMP}'; SET preserve_insertion_order=false;")

    def step(name, sql):
        s = time.time()
        con.execute(sql)
        n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        print(f"  ✓ {name}: {n:,}행 ({time.time() - s:.0f}초)", flush=True)

    print("=== 작은 테이블 ===")
    step("plan", f"""CREATE TABLE plan AS SELECT TRIM(lot_no) lot_no, TRIM(line) line, TRIM(item_cd) item_cd,
        TRIM(grade) grade, TRIM(color) color, TRIM(prd_date) prd_date, {num('ord_qty')}, {num('prd_qty')}
        FROM {csv(A + '/p_prod_plan.csv')} QUALIFY row_number() OVER (PARTITION BY TRIM(lot_no) ORDER BY prd_date DESC) = 1""")
    step("result", f"""CREATE TABLE result AS SELECT TRIM(lot_no) lot_no, TRIM(p_date) p_date, TRIM(line) line,
        TRIM(juya) juya, {num('pr_qty')}, {num('las_qty')}, TRIM(last_flag) last_flag,
        TRY_CAST(input_dt AS TIMESTAMP) input_dt FROM {csv(A + '/p_prod_result.csv')}""")
    step("qmat", f"""CREATE TABLE qmat AS SELECT TRIM(lot_no) lot_no, TRIM(p_date) p_date, TRIM(juya) juya, TRIM(line) line,
        {num('min_val1')}, {num('max_val1')}, {num('set_val1')}, TRIM(acc_fg1) acc_fg1,
        {num('min_val2')}, {num('max_val2')}, {num('set_val2')}, TRIM(acc_fg2) acc_fg2,
        TRY_CAST(input_dt AS TIMESTAMP) input_dt FROM {csv(A + '/mes_qmat_list.csv')}""")
    step("quality", f"""CREATE TABLE quality AS SELECT TRIM(q.lot_no) lot_no, TRIM(q.q_date) q_date, TRIM(q.line) line,
        TRY_CAST(q.bad_qty AS DOUBLE) bad_qty, TRIM(q.bad_cd) bad_cd, COALESCE(c.value_name, TRIM(q.bad_cd)) bad_nm, q.act_desc
        FROM {csv(A + '/q_quality_list.csv')} q
        LEFT JOIN (SELECT TRIM(value_code) value_code, TRIM(value_name) value_name FROM {csv(R + '/c_ref_value.csv')}
                   WHERE TRIM(ref_code)='U040') c ON TRIM(q.bad_cd)=c.value_code""")
    step("mmat", f"""CREATE TABLE mmat AS SELECT TRIM(lot_no) lot_no, TRIM(m_date) m_date, TRIM(item_no) item_no,
        TRIM(item_grade) item_grade, TRIM(item_mode) item_mode, {num('std_qty')}, {num('meas_qty')}
        FROM {csv(A + '/m_mat_list.csv')}""")
    mix_cols = (["lot_no", "bat_no", "p_date"] + [f"item{i:02d}" for i in range(1, 16)] + [f"sitem{i:02d}" for i in range(1, 16)])
    mix_num = [f"cval{i:02d}" for i in range(1, 16)] + [f"sval{i:02d}" for i in range(1, 16)] + \
              [f"cval{i}" for i in range(51, 61)] + [f"sval{i}" for i in range(51, 61)]
    step("mixer", f"""CREATE TABLE mixer AS SELECT {', '.join(f'TRIM({c}) {c}' for c in mix_cols)}, {', '.join(num(c) for c in mix_num)}
        FROM {csv(A + '/HMI_Mixer_list.csv')}""")

    print("=== 피더(압출 운전 기록) — 가장 오래 걸려요 ===", flush=True)
    step("feeder", f"""CREATE TABLE feeder AS SELECT TRIM(lot_no) lot_no, TRIM(p_date) p_date, TRIM(line) line,
        TRY_CAST(input_dt AS TIMESTAMP) ts, TRIM(stop_cd) stop_cd, {', '.join(num(c) for c in FEED_NUM)}
        FROM {csv(A + '/HMI_feeder_list.csv')} ORDER BY lot_no, ts""")
    step("lot_run", """CREATE TABLE lot_run AS SELECT lot_no, any_value(line) line, count(*) n_all,
        count(*) FILTER (WHERE mval02 >= 250) n_run, min(ts) ts_start, max(ts) ts_end,
        min(p_date) p_first, max(p_date) p_last FROM feeder GROUP BY lot_no""")
    con.execute("CHECKPOINT")
    con.close()
    for f in os.listdir(TMP):
        os.remove(os.path.join(TMP, f))
    print(f"\n완료! {time.time() - t0:.0f}초 → {DB} ({os.path.getsize(DB) / 1e9:.2f}GB)")

if __name__ == "__main__":
    main()
