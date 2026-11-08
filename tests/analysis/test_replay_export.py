import json
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch
import unittest
from datetime import date
import duckdb
import pandas as pd

import slp.analysis.forecast as forecast
import slp.analysis.replay as replay
import slp.analysis.data_quality as data_quality
from slp.common.number_format import number, text
from slp.reporting.export import build
import slp.common.table_display as TD


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.db=duckdb.connect(':memory:')
        data=[]
        for day in range(1,14):
            for minute in range(60):
                data.append({'lot_no':'L','line':'11','p_date':f'2026.01.{day:02d}',
                             'ts':pd.Timestamp(2026,1,day,12)+pd.Timedelta(minutes=minute),
                             'mval02':500.,'mval03':float(day+100),'mval01':-600.,'cval08':200.})
        frame=pd.DataFrame(data)
        self.db.execute('CREATE TABLE feeder AS SELECT * FROM frame')
        self.db.execute("CREATE TABLE plan AS SELECT 'L' lot_no,'11' line,'G' grade,'C' color")
        self.db.execute("CREATE TABLE lot_run AS SELECT '11' line UNION SELECT '12'")
        self.db.execute('CREATE TABLE quality(line VARCHAR,q_date VARCHAR,bad_qty DOUBLE)')
        self.db.execute('CREATE TABLE result(lot_no VARCHAR,line VARCHAR,p_date VARCHAR,juya VARCHAR,pr_qty DOUBLE,input_dt TIMESTAMP)')
        self.db.execute("INSERT INTO result VALUES ('L','11','2026.01.10','1',1000,'2026-01-10 18:00:00'),('L','11','2026.01.09','2',1000,'2026-01-12 12:00:00')")
        self.query=lambda sql,params=None:self.db.execute(sql,params or []).df()
        replay.predict.clear();replay.actuals.clear();data_quality.snapshot.clear()

    def tearDown(self):
        self.db.close()
        replay.predict.clear();replay.actuals.clear();data_quality.snapshot.clear()

    def test_future_measurement_changes_cannot_change_frozen_forecast(self):
        with patch('slp.analysis.forecast.q',self.query):
            res={'line':'11','기간':(date(2026,1,1),date(2026,1,10))}
            before=forecast.analyze(res,'equipment')
            self.assertEqual(len(before['예측']),12)
            self.assertLessEqual(before['이력']['일자'].max().date(),date(2026,1,10))
            self.db.execute("UPDATE feeder SET mval03=9999 WHERE p_date>'2026.01.10'")
            after=forecast.analyze(res,'equipment')
            pd.testing.assert_frame_equal(before['예측'],after['예측'])
        with patch('slp.analysis.replay.LA.q',self.query):
            observed=replay.actuals('11','G','C',date(2026,1,10))
        self.assertEqual(observed['예측일'].min(),date(2026,1,11))
        result=replay.evaluate(before['예측'],observed)
        self.assertTrue(result.loc[result['항목']=='전류','절대오차'].gt(9000).all())

    def test_quality_excludes_late_entered_results(self):
        with patch('slp.analysis.data_quality.q',self.query):
            d=data_quality.snapshot('11',date(2026,1,1),date(2026,1,10),cutoff=replay.end_of_production_day(date(2026,1,10)))
        self.assertEqual(d['요약']['전체 운전 기록'],600)
        self.assertEqual(d['요약']['기록 부족 교대'],1)
        self.assertEqual(d['교대'].iloc[0]['생산일'],'2026.01.10')

    def test_overview_keeps_unrecorded_lines_and_bounds_results(self):
        import slp.analysis.equipment_overview as overview
        with patch('slp.analysis.equipment_overview.q',self.query):
            data=overview.analyze.__wrapped__(date(2026,1,1),date(2026,1,10),replay.end_of_production_day(date(2026,1,10)))
        self.assertEqual(set(data['line']),{'11','12'})
        measured=data[data.line=='11'].iloc[0]
        self.assertEqual(measured['kg'],1000)
        self.assertEqual(measured['기록수'],600)
        absent=data[data.line=='12'].iloc[0]
        self.assertTrue(pd.isna(absent['가동률_%']))
        self.assertIn('운전 기록 없음',absent['확인사항'])

    def test_missing_future_actual_is_not_zero_or_error(self):
        p=pd.DataFrame([{'항목':'전류','예측일':date(2026,1,11),'참고 예측값':100.,'참고 하한':90.,'참고 상한':110.}])
        observed=pd.DataFrame(columns=['항목','예측일','이후 실측','기록수'])
        d=replay.evaluate(p,observed)
        self.assertTrue(pd.isna(d.iloc[0]['절대오차']))
        self.assertEqual(d.iloc[0]['비교상태'],'이후 동일 제품 실측 없음')


class ExportFormatTests(unittest.TestCase):
    def test_values_and_trailing_zeros(self):
        for val,expected in [(100.,'100'),(12.30,'12.3'),(0.,'0'),(.005,'0.01'),(1234.56,'1,234.56'),(493.93333333333334,'493.93'),(187.63333333333333,'187.63'),(-0.001,'0'),(-0.09,'-0.09'),(-650.,'-650'),(-0.,'0')]:
            self.assertEqual(number(val),expected)
        self.assertEqual(number(None),'—')
        self.assertEqual(text('가동 493.93333333333334 h / 변화 1.234567%'), '가동 493.93 h / 변화 1.23%')
        self.assertEqual(text('MI 2.0 (규격 1.5~2.50), 2026.08.03'),'MI 2 (규격 1.5~2.5), 2026.08.03')
        data=pd.DataFrame({'값':[100.,12.30]})
        pretty=TD.pretty(data)
        self.assertEqual(pretty._translate(False,False)['body'][1][1]['display_value'],'12.3')
        self.assertEqual(data.iloc[1,0],12.30)

    def test_timestamp_units_display_and_export(self):
        for unit in ('us', 'ns'):
            stamp = pd.Timestamp('2026-08-31 23:59:00.123')
            frame = pd.DataFrame({'최종기록': pd.Series([stamp, pd.NaT], dtype=f'datetime64[{unit}]')})
            shown = TD.pretty(frame)._translate(False, False)['body']
            self.assertEqual(shown[0][1]['display_value'], '2026-08-31 23:59:00.123')
            self.assertEqual(shown[1][1]['display_value'], '—')
            doc, bundle = build('시각', {}, {'기록': frame}, {})
            self.assertIn('2026-08-31 23:59:00.123', doc)
            with ZipFile(BytesIO(bundle)) as z:
                payload = json.loads(z.read('report.json'))
                self.assertEqual(payload['표']['기록'][0]['최종기록'], stamp.isoformat())
            self.assertEqual(frame['최종기록'].dtype, f'datetime64[{unit}]')

    def test_export_is_escaped_portable_and_exact(self):
        frame=pd.DataFrame({'LOT':['00123'],'값':[12.3456789],'설명':['<script>alert(1)</script>']})
        doc,bundle=build('리포트',{'마감':'2026-01-10'},{'결과':frame},{'종합 주의사항':'확인 필요'})
        self.assertIn('12.35',doc)
        self.assertNotIn('12.3456789',doc)
        self.assertNotIn('<script>',doc)
        self.assertIn('&lt;script&gt;',doc)
        with ZipFile(BytesIO(bundle)) as z:
            payload=json.loads(z.read('report.json'))
            self.assertEqual(payload['표']['결과'][0]['LOT'],'00123')
            self.assertEqual(payload['표']['결과'][0]['값'],12.3456789)
            self.assertIn('종합 주의사항',z.read('report.html').decode())
            self.assertEqual(len(z.namelist()),3)


if __name__=='__main__':
    unittest.main()
