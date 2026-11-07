"""Read selected observations without changing MES values or crossing replay cutoffs."""
from dataclasses import dataclass
from zoneinfo import ZoneInfo
import math
import pandas as pd

from lot_analysis import q
from aistream_client import Client, Config, AIStreamError, SCOPE, REFERENCE, encoded

KST = ZoneInfo('Asia/Seoul')
MAX_BATCH_ROWS = 6000
MAX_BATCH_BYTES = 900000


def local_time(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize(KST) if ts.tzinfo is None else ts.tz_convert(KST)


def day_end(value):
    return local_time(value) + pd.Timedelta(days=1, hours=8, minutes=30) - pd.Timedelta(microseconds=1)


@dataclass(frozen=True)
class Selection:
    kind: str
    cutoff: str
    lot: str = ''
    line: str = ''
    start: str = ''
    end: str = ''

    @classmethod
    def lot_scope(cls, lot, cutoff):
        return cls('lot', local_time(cutoff).isoformat(), lot=str(lot))

    @classmethod
    def period(cls, start, end, line='', cutoff=None):
        return cls('equipment' if line else 'overview',
            local_time(cutoff if cutoff is not None else day_end(end)).isoformat(),
            line=str(line), start=str(start)[:10], end=str(end)[:10])


def prepare(selection):
    summary = {'분석유형': selection.kind, 'LOT': selection.lot or None,
        '선택호기': selection.line or ('LOT 연계호기' if selection.lot else '전체 호기'), '분석기간': [selection.start, selection.end],
        '마감시각': selection.cutoff, '모델적용범위': dict(SCOPE),
        '모델기준확정일': REFERENCE, '선택기록': 0, '적용범위기록': 0,
        '연결불가·범위밖기록': 0, '기준확정전기록': 0, '전송기록': 0, '로컬보류구간': 0}
    if selection.line and selection.line != SCOPE['line']:
        return summary, pd.DataFrame(), '선택 호기는 모델 적용 범위 밖입니다. 현재 모델은 06호기 / SR-0310FMU / NP에만 적용됩니다.'
    where, params = ['f.ts IS NOT NULL', 'f.ts<=?'], [local_time(selection.cutoff).tz_localize(None)]
    if selection.lot:
        where.append('f.lot_no=?'); params.append(selection.lot)
    if selection.line:
        where.append('f.line=?'); params.append(selection.line)
    if selection.start:
        where.append('f.p_date BETWEEN ? AND ?')
        params.extend([selection.start.replace('-', '.'), selection.end.replace('-', '.')])
    # Build one unambiguous mapping before filtering for the pilot product.
    cte = '''WITH mapping AS (
        SELECT lot_no,line,min(grade) grade,min(color) color FROM plan
        GROUP BY lot_no,line HAVING count(DISTINCT (grade,color))=1)
        , selected AS (
        SELECT f.line,f.lot_no,f.ts,f.mval02,f.mval03,f.mval01,p.grade,p.color
        FROM feeder f LEFT JOIN mapping p ON p.lot_no=f.lot_no AND p.line=f.line
        WHERE ''' + ' AND '.join(where) + ') '
    match = 'line=? AND grade=? AND color=?'
    scope_args = list(SCOPE.values())
    reference = local_time(REFERENCE).tz_localize(None)
    counts = q(cte + f'''SELECT count(*) total,
        count(*) FILTER(WHERE {match}) applicable,
        count(*) FILTER(WHERE {match} AND ts<?) early FROM selected''',
        params + scope_args + scope_args + [reference]).iloc[0]
    summary.update({'선택기록': int(counts['total']), '적용범위기록': int(counts['applicable']),
        '연결불가·범위밖기록': int(counts['total']-counts['applicable']),
        '기준확정전기록': int(counts['early'])})
    if not counts['total']:
        return summary, pd.DataFrame(), '선택 범위의 마감 이전 운전 기록이 없습니다. AIStream 평가는 보류합니다.'
    if not counts['applicable']:
        return summary, pd.DataFrame(), '선택 범위에 06호기 / SR-0310FMU / NP로 연결되는 기록이 없어 AIStream 평가는 보류합니다.'
    if counts['applicable'] == counts['early']:
        return summary, pd.DataFrame(), '모델 기준 확정일(2026-10-01) 이전 기록입니다. 미래 참고자료 혼입을 막기 위해 AIStream 평가는 보류합니다.'
    frame = q(cte + f'SELECT * FROM selected WHERE {match} AND ts>=? ORDER BY ts,lot_no',
              params + scope_args + [reference])
    return summary, frame.sort_values(['ts', 'lot_no'], kind='stable'), ''


def batches(frame, cutoff, max_rows=MAX_BATCH_ROWS, max_bytes=MAX_BATCH_BYTES):
    """Whole ten-minute LOT windows stay in the same request, including duplicates/stops."""
    groups, oversized = [], []
    overhead = len(encoded({'as_of': cutoff, 'records': []}))
    frame = frame.assign(_window=pd.to_datetime(frame['ts']).dt.floor('10min'))
    for (lot, start), group in frame.groupby(['lot_no', '_window'], sort=True):
        records = []
        for row in group.to_dict('records'):
            record = {k: str(row[k]) for k in ('line', 'grade', 'color', 'lot_no')}
            record['ts'] = local_time(row['ts']).isoformat()
            for key in ('mval02', 'mval03', 'mval01'):
                value = row[key]
                record[key] = float(value) if pd.notna(value) and math.isfinite(value) else None
            records.append(record)
        size = len(encoded(records))-2
        if len(records) > max_rows or overhead + size > max_bytes:
            oversized.append({'LOT': str(lot), '시작': local_time(start).isoformat(),
                '기록수': len(records), '상태': '평가 보류', '보류사유': '단일 10분 구간이 요청 크기 제한을 초과함'})
        else:
            groups.append((records, size))
    requests, current, current_bytes = [], [], overhead
    for group, size in groups:
        if current and (len(current)+len(group) > max_rows or
                current_bytes+size+1 > max_bytes):
            requests.append({'as_of': cutoff, 'records': current}); current = []; current_bytes = overhead
        current_bytes += size + int(bool(current))
        current.extend(group)
    if current:
        requests.append({'as_of': cutoff, 'records': current})
    return requests, oversized


def analyze(selection, config=None, on_progress=None, client=None):
    summary, frame, reason = prepare(selection)
    outcome = {'요약': summary, '완료': False, '보류': reason, '오류': '', '응답': [], '요청크기보류': []}
    if reason:
        return outcome
    requests, oversized = batches(frame, selection.cutoff)
    outcome['요청크기보류'] = oversized
    summary['로컬보류구간'] = len(oversized)
    summary['요청수'] = len(requests)
    connection = client or Client(config or Config.from_env())
    for i, payload in enumerate(requests):
        if on_progress:
            on_progress(i+1, len(requests))
        summary['전송기록'] += len(payload['records'])
        try:
            data = connection.predict(payload)
            if outcome['응답'] and data['candidate_threshold'] != outcome['응답'][0]['candidate_threshold']:
                raise AIStreamError('분할 요청 사이에 모델 기준이 변경됐습니다. 분석을 다시 실행하세요.')
        except AIStreamError as exc:
            outcome['오류'] = str(exc)
            break
        outcome['응답'].append(data)
    outcome['완료'] = len(outcome['응답']) == len(requests) and not oversized and not outcome['오류']
    rows = [r for response in outcome['응답'] for r in response['results']]
    summary.update({'응답요청수': len(outcome['응답']), '응답구간': len(rows),
        '응답기록': sum(r['data_quality']['input_records'] for r in outcome['응답']),
        '평가구간': sum(r['candidate'] is not None for r in rows),
        '이상후보': sum(r['candidate'] is True for r in rows),
        '서버보류구간': sum(r['candidate'] is None for r in rows),
        '총보류구간': sum(r['candidate'] is None for r in rows)+len(oversized),
        '미응답요청수': len(requests)-len(outcome['응답'])})
    if not requests:
        outcome['보류'] = '요청 크기 제한을 넘는 구간만 있어 AIStream 평가는 보류합니다.'
    return outcome


def tables(outcome):
    rows, measurements = [], []
    for response in outcome.get('응답', []):
        for r in response['results']:
            rows.append({'호기': r['line'], 'LOT': r['lot_no'], 'Grade': r['grade'], 'Color': r['color'],
                '시작': pd.Timestamp(r['window_start']), '종료': pd.Timestamp(r['window_end']),
                '기록수': r['records'], '상태': r['status'], '이상 점수': r['anomaly_score'],
                '참고 백분위': r.get('reference_percentile'), '보류사유': ' / '.join(r['reasons'])})
            for m in r.get('related_measurements', []):
                measurements.append({'LOT': r['lot_no'], '시작': pd.Timestamp(r['window_start']),
                    '항목': m['label'], '관측값': m['observed'], '과거 중앙값': m['reference_median'],
                    '과거 5%': m['reference_q05'], '과거 95%': m['reference_q95'], '비교 방향': m['direction']})
    return {'AIStream 분석 요약': pd.DataFrame([outcome['요약']]),
        'AIStream 구간별 결과': pd.DataFrame(rows), 'AIStream 관련 운전값': pd.DataFrame(measurements),
        'AIStream 요청 크기 보류': pd.DataFrame(outcome.get('요청크기보류', []))}


def export_parts(outcome):
    summary = outcome['요약']
    description = (f"AIStream 실제 API 응답. 평가 {summary.get('평가구간', 0)}개 구간, 이상 후보 {summary.get('이상후보', 0)}개. "
        if outcome.get('응답') else 'AIStream 평가 결과 없음. ')
    description += ' '.join(x for x in (outcome.get('보류'), outcome.get('오류')) if x)
    description += ' 관측 패턴의 검토 후보이며 미래 예측·고장 확률·품질 판정이 아닙니다. 범위 밖 기록은 미평가입니다.'
    return ({'AIStream 완료': outcome['완료'], 'AIStream 분석조건': summary,
        'AIStream 보류': outcome.get('보류'), 'AIStream 오류': outcome.get('오류'),
        'AIStream 원래 응답': outcome.get('응답', [])}, tables(outcome), {'AIStream 운전 패턴 분석': description})
