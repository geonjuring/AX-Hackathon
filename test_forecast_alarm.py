"""Run with: python -m unittest discover -s lot_agent -p 'test_*.py'."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import forecast
from demo_alarm import _create, advance, PEOPLE


class ForecastTests(unittest.TestCase):
    def history(self, count=10):
        dates = pd.date_range('2026-08-01', periods=count)
        return pd.DataFrame({'일자': dates, **{m: np.arange(count, dtype=float) + 100 for m in forecast.METRICS}})

    def test_known_trend_and_sparse_history(self):
        r = forecast.project(self.history(), '2026-08-10')
        self.assertEqual(len(r), 12)
        self.assertEqual(r.iloc[0]['참고 예측값'], 110)
        self.assertEqual(r.iloc[2]['참고 예측값'], 112)
        self.assertTrue(forecast.project(self.history(6), '2026-08-06').empty)
        self.assertTrue(forecast.project(self.history(), '2026-09-01').empty)

    def test_missing_metric_does_not_invent_values(self):
        h = self.history()
        h['전류'] = np.nan
        r = forecast.project(h, '2026-08-10')
        self.assertNotIn('전류', set(r['항목']))
        self.assertEqual(len(r), 9)

    def test_lot_query_uses_own_cutoff_and_same_product(self):
        with patch('forecast.q', return_value=pd.DataFrame(columns=['일자',*forecast.METRICS])) as query:
            cutoff = pd.Timestamp('2026-08-10 12:34')
            r = forecast.analyze({'info': {'line':'11','grade':'G','color':'C','p_last':'2026.08.10','ts_end':cutoff}}, 'lot')
            sql, params = query.call_args.args
            self.assertIn('f.ts<=?', sql)
            self.assertIn('f.p_date BETWEEN ? AND ?', sql)
            self.assertIn(cutoff, params)
            self.assertEqual(params[-2:], ['G','C'])
            self.assertTrue(r['예측'].empty)


class AlarmTests(unittest.TestCase):
    def test_escalation_ack_and_resolution(self):
        state = {'시연분':0, '알림':[]}
        _create(state, 'test', 5)
        _create(state, 'test', 5)
        self.assertEqual(len(state['알림']), 1)
        a = state['알림'][0]
        advance(state, 4); self.assertEqual(a['단계'], 0)
        advance(state, 1); self.assertEqual(a['단계'], 1)
        a['상태'] = '확인'
        advance(state, 30); self.assertEqual(a['단계'], 1)
        a['상태'] = '해제'
        advance(state, 30); self.assertEqual(a['단계'], 1)
        _create(state, 'test', 5)
        advance(state, 10); self.assertEqual(state['알림'][1]['단계'], 2)
        self.assertTrue(all(p['원본_직급']=='미확인' and p['이름'].startswith('가상 직원') for p in PEOPLE))


if __name__ == '__main__':
    unittest.main()
