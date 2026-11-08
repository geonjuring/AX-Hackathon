"""Read-only, cutoff-bounded trend estimates. No failure probability or safety limit."""
import numpy as np
import pandas as pd
from slp.analysis.lot_analysis import q, RUN_RPM

METRICS = {'전류': 'mval03', '진공': 'mval01', '메인모터 RPM': 'mval02', 'Melt 온도': 'cval08'}


def project(history, cutoff):
    rows = []
    for name in METRICS:
        d = history[['일자', name]].dropna().tail(30).copy()
        if len(d) < 7:
            continue
        dates = pd.to_datetime(d['일자'])
        if (pd.Timestamp(cutoff).normalize() - dates.max()).days > 7 or dates.diff().dt.days.max() > 7:
            continue
        x = (dates - dates.min()).dt.days.to_numpy(dtype=float)
        y = d[name].to_numpy(dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        residual = float(np.sqrt(np.mean((y - (intercept + slope * x)) ** 2)))
        for day in range(1, 4):
            target = pd.Timestamp(cutoff).normalize() + pd.Timedelta(days=day)
            value = float(intercept + slope * (target - dates.min()).days)
            if not np.isfinite(value):
                continue
            rows.append({'항목': name, '예측일': target.date(), '참고 예측값': round(value, 2),
                         '참고 하한': round(value - 2 * residual, 2), '참고 상한': round(value + 2 * residual, 2),
                         '최근 실측': round(float(y[-1]), 2), '일별 변화': round(float(slope), 3), '관측일수': len(d)})
    return pd.DataFrame(rows)


def analyze(res, kind):
    if kind == 'lot':
        info = res['info']
        cutoff = info.get('ts_end')
        if cutoff is None or pd.isna(cutoff):
            return {'보류': 'LOT 종료 시각이 없어 미래 데이터 혼입을 방지하기 위해 예측을 보류합니다.', '예측': pd.DataFrame()}
        line, grade, color = info.get('line'), info.get('grade'), info.get('color')
        end_day = info.get('p_last') or info.get('생산일_마지막')
    else:
        line = res['line']
        end_day = res['기간'][1].strftime('%Y.%m.%d')
        # MES production day includes the following morning's night shift.
        cutoff = pd.Timestamp(res['기간'][1]) + pd.Timedelta(days=1, hours=8, minutes=30) - pd.Timedelta(microseconds=1)
        latest = q('''SELECT p.grade, p.color FROM feeder f JOIN plan p USING(lot_no)
                      WHERE f.line=? AND f.p_date<=? AND f.ts<=? AND f.mval02>=?
                      ORDER BY f.ts DESC LIMIT 1''', [line, end_day, cutoff, RUN_RPM])
        if latest.empty:
            return {'보류': '동일 제품의 운전 기록이 없어 예측을 보류합니다.', '예측': pd.DataFrame()}
        grade, color = latest.iloc[0][['grade', 'color']]
    if not grade or pd.isna(grade) or not color or pd.isna(color) or not end_day:
        return {'보류': '호기·제품·생산일 정보가 부족해 예측을 보류합니다.', '예측': pd.DataFrame()}
    start_day = (pd.to_datetime(str(end_day).replace('.', '-')) - pd.Timedelta(days=59)).strftime('%Y.%m.%d')
    cols = ', '.join(f'quantile_cont(f.{col},0.5) "{name}"' for name, col in METRICS.items())
    history = q(f'''SELECT f.p_date 일자, count(*) 기록수, {cols} FROM feeder f
        WHERE f.line=? AND f.p_date BETWEEN ? AND ? AND f.ts<=? AND f.mval02>=?
        AND EXISTS (SELECT 1 FROM plan p WHERE p.lot_no=f.lot_no AND p.grade=? AND p.color=?)
        GROUP BY f.p_date HAVING count(*)>=60 ORDER BY f.p_date''',
        [line, start_day, end_day, cutoff, RUN_RPM, grade, color])
    history['일자'] = pd.to_datetime(history['일자'].str.replace('.', '-', regex=False))
    predictions = project(history, end_day.replace('.', '-'))
    return {'호기': line, 'Grade': grade, 'Color': color, '예측': predictions, '이력': history, '기준시각': cutoff, '제품': f'{line}호기 · {grade} / {color}',
            '보류': '' if not predictions.empty else '조건이 같은 유효 관측일이 7일 미만이거나 기록 간격이 7일을 초과하여 예측을 보류합니다.'}
