"""
설비 이상 분석용 데이터 추가 (prep.py 다음에 실행, 1~2분)
slp.duckdb 에 rpt(생산일보), rpt_dtl(호기별 일보), power(EX 모터·히터 전력 15분) 테이블 추가
실행:  python -m scripts.prepare.prep_equip
"""
import os, re, time, duckdb
import pandas as pd

from slp.config import DATA_DIR, DB_PATH, RUNTIME_DIR
DATA = str(DATA_DIR)
A, R = f"{DATA}/01_분석용", f"{DATA}/02_기준정보"
DB = str(DB_PATH)

def csv(p):
    return f"read_csv('{p}', all_varchar=true, header=true, sample_size=-1)"

def sensor_line(name):
    n = str(name)
    m = re.match(r"\s*EX\s*(\d+)", n, re.I) or re.search(r"압출\s*(\d+)\s*호기", n)
    if m:
        return f"{int(m.group(1)):02d}", "모터"
    m = re.match(r"\s*(\d+)\s*호기\s*히터", n)
    if m:
        return f"{int(m.group(1)):02d}", "히터"
    return None, None

def main():
    t0 = time.time()
    if not os.path.exists(DB):
        raise SystemExit("slp.duckdb 가 없습니다. 먼저 python -m scripts.prepare.prep 를 실행하세요.")
    con = duckdb.connect(DB)
    con.execute("SET memory_limit='1500MB'; SET threads=2")
    for t in ("rpt", "rpt_dtl", "power", "sensor_map"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.execute(f"""CREATE TABLE rpt AS SELECT TRIM(p_date) p_date, TRIM(fac_cd) fac_cd, TRIM(juya) juya,
        facil_desc1, facil_desc2, spe_desc1, spe_desc2 FROM {csv(A + '/p_prod_rpt.csv')}""")
    con.execute(f"""CREATE TABLE rpt_dtl AS SELECT TRIM(p_date) p_date, TRIM(juya) juya, TRIM(line) line,
        TRY_CAST(pr_qty AS DOUBLE) pr_qty, prod_desc1, prod_desc2, TRY_CAST(notwk_time AS DOUBLE) notwk_time
        FROM {csv(A + '/p_prod_rpt_dtl.csv')}""")
    meta = con.execute(f"SELECT TRIM(sensor_id) sensor_id, name FROM {csv(R + '/tbl_sensor_meta.csv')}").df()
    meta[["line", "구분"]] = meta["name"].apply(lambda n: pd.Series(sensor_line(n)))
    meta = meta.dropna(subset=["line"])
    con.register("m", meta)
    con.execute("CREATE TABLE sensor_map AS SELECT * FROM m")
    con.execute(f"""CREATE TABLE power AS SELECT s.line, s.구분, TRIM(p.sensor_id) sensor_id, p.센서명,
        TRY_CAST(p.일시 AS TIMESTAMP) ts, TRY_CAST(p.평균_kW AS DOUBLE) kw, TRY_CAST(p.사용량_kWh AS DOUBLE) kwh
        FROM {csv(A + '/EMS_전력계_15min집계.csv')} p JOIN sensor_map s ON TRIM(p.sensor_id)=s.sensor_id""")
    for t in ("rpt", "rpt_dtl", "sensor_map", "power"):
        print(f"  ✓ {t}: {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:,}행")
    print(con.execute("SELECT 구분, count(DISTINCT line) 호기수, string_agg(DISTINCT line, ',' ORDER BY line) 호기 FROM sensor_map GROUP BY 1").df().to_string(index=False))
    con.execute("CHECKPOINT"); con.close()
    print(f"완료 {time.time() - t0:.0f}초")

if __name__ == "__main__":
    main()
