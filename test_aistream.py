"""Integration boundaries: replay isolation, complete windows, protocol and partial failures."""
from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from zipfile import ZipFile
import urllib.error
import duckdb
import pandas as pd

import aistream_analysis as A
from aistream_client import Client, Config, AIStreamError, SCOPE, SCHEMA, MODEL, REFERENCE, validate, encoded
from report_export import build


def response(payload):
    groups = {}
    for r in payload['records']:
        stamp = pd.Timestamp(r['ts']).floor('10min')
        groups.setdefault((r['lot_no'], stamp), []).append(r)
    rows = [dict(SCOPE, lot_no=lot, window_start=start.isoformat(),
        window_end=(start+pd.Timedelta(minutes=10)).isoformat(), records=len(records),
        status='참고 패턴 범위', candidate=False, anomaly_score=0.3123456789,
        reference_percentile=39.5, reasons=[], related_measurements=[])
        for (lot, start), records in groups.items()]
    return {'schema_version': SCHEMA, 'model_version': MODEL, 'scope': dict(SCOPE),
        'as_of': payload['as_of'], 'reference_available_after': REFERENCE,
        'candidate_threshold': .65, 'results': rows, 'limitations': ['검토용'],
        'data_quality': {'input_records': len(payload['records']), 'total_windows': len(rows),
                         'evaluated_windows': len(rows), 'withheld_windows': 0}}


class RecordingClient:
    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at

    def predict(self, payload):
        self.calls.append(payload)
        if len(self.calls) == self.fail_at:
            raise AIStreamError('테스트용 응답 시간 초과')
        return response(payload)


class DataBoundaries(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect(':memory:')
        frame = pd.DataFrame([{'lot_no': '00123', 'line': '06', 'p_date': '2026.10.02',
            'ts': pd.Timestamp('2026-10-02 12:00')+pd.Timedelta(minutes=10*w+i),
            'mval02': 500., 'mval03': 0., 'mval01': -640.} for w in range(3) for i in range(8)])
        self.db.execute('CREATE TABLE feeder AS SELECT * FROM frame')
        self.db.execute("CREATE TABLE plan AS SELECT '00123' lot_no, '06' line, 'SR-0310FMU' grade, 'NP' color")
        self.query = lambda sql, params=None: self.db.execute(sql, params or []).df()
        self.patch = patch('aistream_analysis.q', self.query)
        self.patch.start()

    def tearDown(self):
        self.patch.stop(); self.db.close()

    def test_replay_cutoff_and_future_mutation_do_not_change_inputs(self):
        selection = A.Selection.lot_scope('00123', '2026-10-02T12:10:00+09:00')
        summary, before, _ = A.prepare(selection)
        self.assertEqual(len(before), 9)
        self.db.execute("UPDATE feeder SET mval03=9999 WHERE ts>'2026-10-02 12:10'")
        _, after, _ = A.prepare(selection)
        pd.testing.assert_frame_equal(before, after)
        self.assertTrue((before.ts <= pd.Timestamp('2026-10-02 12:10')).all())
        self.assertEqual(A.batches(before, selection.cutoff)[0], A.batches(after, selection.cutoff)[0])

    def test_plan_duplicates_do_not_duplicate_records_and_ambiguous_product_is_withheld(self):
        self.db.execute('INSERT INTO plan SELECT * FROM plan')
        selection = A.Selection.period(date(2026, 10, 2), date(2026, 10, 2))
        _, frame, _ = A.prepare(selection)
        self.assertEqual(len(frame), 24)
        self.db.execute("INSERT INTO plan VALUES ('00123','06','OTHER','NP')")
        summary, frame, reason = A.prepare(selection)
        self.assertTrue(frame.empty)
        self.assertEqual(summary['연결불가·범위밖기록'], 24)
        self.assertTrue(reason)

    def test_scope_and_reference_hold_do_not_call_service(self):
        client = RecordingClient()
        for selection in [A.Selection.period(date(2026, 10, 2), date(2026, 10, 2), line='07'),
                          A.Selection.lot_scope('00123', '2026-09-30T23:00:00+09:00')]:
            result = A.analyze(selection, client=client)
            self.assertFalse(result['완료'])
            self.assertTrue(result['보류'])
        self.assertFalse(client.calls)
        self.db.execute("UPDATE feeder SET ts=ts-INTERVAL '3 days',p_date='2026.09.29'")
        result = A.analyze(A.Selection.lot_scope('00123', '2026-10-02T13:00:00+09:00'), client=client)
        self.assertIn('기준 확정일', result['보류'])
        self.assertFalse(client.calls)

    def test_batching_keeps_windows_duplicates_stops_zero_and_negative_values(self):
        selection = A.Selection.lot_scope('00123', '2026-10-02T13:00:00+09:00')
        _, frame, _ = A.prepare(selection)
        frame.loc[frame.index[0], 'mval02'] = 0
        frame.loc[frame.index[1], 'mval03'] = float('nan')
        requests, held = A.batches(frame, selection.cutoff, max_rows=12)
        self.assertEqual([len(p['records']) for p in requests], [8, 8, 8])
        self.assertFalse(held)
        self.assertEqual(requests[0]['records'][0]['lot_no'], '00123')
        self.assertEqual(requests[0]['records'][0]['mval02'], 0)
        self.assertEqual(requests[0]['records'][0]['mval01'], -640)
        self.assertIsNone(requests[0]['records'][1]['mval03'])
        limit = len(encoded(requests[0]))+10
        byte_requests, _ = A.batches(frame, selection.cutoff, max_bytes=limit)
        self.assertEqual(len(byte_requests), 3)
        self.assertTrue(all(len(encoded(p)) <= limit for p in byte_requests))
        requests, held = A.batches(frame, selection.cutoff, max_rows=4)
        self.assertFalse(requests)
        self.assertEqual(sum(r['기록수'] for r in held), 24)

    def test_failed_second_batch_preserves_partial_result_and_marks_incomplete(self):
        selection = A.Selection.lot_scope('00123', '2026-10-02T13:00:00+09:00')
        client = RecordingClient(fail_at=2)
        original = A.batches
        with patch('aistream_analysis.batches', side_effect=lambda f, t: original(f, t, max_rows=12)):
            result = A.analyze(selection, client=client)
        self.assertFalse(result['완료'])
        self.assertTrue(result['오류'])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(result['요약']['전송기록'], 16)
        self.assertEqual(result['요약']['응답기록'], 8)
        self.assertEqual(result['요약']['평가구간'], 1)

    def test_export_preserves_exact_values_response_and_scope(self):
        result = A.analyze(A.Selection.lot_scope('00123', '2026-10-02T13:00:00+09:00'), client=RecordingClient())
        metadata, tables, paragraphs = A.export_parts(result)
        document, bundle = build('분석', metadata, tables, {**paragraphs, '종합 주의사항': '검토용'})
        self.assertIn('AIStream 구간별 결과', document)
        with ZipFile(BytesIO(bundle)) as z:
            exported = json.loads(z.read('report.json'))
        self.assertEqual(exported['표']['AIStream 구간별 결과'][0]['이상 점수'], 0.3123456789)
        self.assertEqual(exported['분석조건']['AIStream 원래 응답'][0]['scope'], SCOPE)


class ProtocolTests(unittest.TestCase):
    def payload(self):
        return {'as_of': '2026-10-02T13:00:00+09:00', 'records': [dict(SCOPE,
            lot_no='00123', ts='2026-10-02T12:00:00+09:00', mval02=500., mval03=0., mval01=-640.)]}

    def test_wrong_scope_missing_windows_and_inconsistent_decision_are_rejected(self):
        payload = self.payload()
        good = response(payload)
        self.assertIs(validate(good, payload), good)
        for mutate in [lambda x: x['scope'].update(line='07'),
                       lambda x: x['results'].clear(),
                       lambda x: x['results'][0].update(candidate=True),
                       lambda x: x['results'][0].update(anomaly_score=float('inf'))]:
            bad = deepcopy(good); mutate(bad)
            with self.assertRaises(AIStreamError): validate(bad, payload)

    def test_http_error_and_timeout_are_not_retried_or_converted_to_normal(self):
        for failure in [TimeoutError(), urllib.error.HTTPError('https://example.invalid', 503, 'not ready', {}, BytesIO())]:
            client = Client(Config())
            with patch.object(client.opener, 'open', side_effect=failure) as call:
                with self.assertRaises(AIStreamError): client.predict(self.payload())
                self.assertEqual(call.call_count, 1)

    def test_invalid_configuration_is_rejected(self):
        for settings in [{'AISTREAM_BASE_URL': 'http://example.com'},
                         {'AISTREAM_BASE_URL': 'https://user:secret@example.com'},
                         {'AISTREAM_TIMEOUT_SECONDS': 'nan'}]:
            with patch.dict('os.environ', settings, clear=True):
                with self.assertRaises(AIStreamError): Config.from_env()


if __name__ == '__main__':
    unittest.main()
