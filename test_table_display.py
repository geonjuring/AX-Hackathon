import unittest
import pandas as pd
import table_display as td


class ComparisonTests(unittest.TestCase):
    def test_direction_handles_signed_missing_and_boundaries(self):
        self.assertEqual(td.direction(-650, -600), td.LOW)
        self.assertEqual(td.direction(-550, -600), td.HIGH)
        self.assertEqual(td.direction(210, 200, 10), '')
        self.assertEqual(td.direction(190, 200, 10), '')
        self.assertEqual(td.direction(189, 200, 10), td.LOW)
        for value in [None, float('nan'), float('inf'), '미측정']:
            self.assertEqual(td.direction(value, 10), '')

    def test_physical_uses_spec_and_leaves_unmeasured_unstyled(self):
        self.assertEqual(td.physical_style('1.0 (1.5~2.5)'), td.LOW)
        self.assertEqual(td.physical_style('3.0 (1.5~2.5)'), td.HIGH)
        for value in ['1.5 (1.5~2.5)', '2.5 (1.5~2.5)', '미측정 (1.5~2.5)', '1.0 (-~-)']:
            self.assertEqual(td.physical_style(value), '')

    def test_recipe_matches_reference_within_same_lot(self):
        data = pd.DataFrame({'lot_no':['A','B'], '원료':['x','x'], '기준':[10, 100], '실측':[11, 99], '차이율':[10, -1]})
        styler = td.recipe(data, ['원료'], ['기준','실측','차이율'], '실측', '기준')
        rendered = styler._compute()
        for lot, color in [('A','#f87171'), ('B','#60a5fa')]:
            cell = (0, styler.data.columns.get_loc(('실측',lot)))
            self.assertIn(('color',color), rendered.ctx[cell])

    def test_missing_standard_remains_pending_and_source_preserved(self):
        source = pd.DataFrame([{'항목':'배럴 온도', '판정':'기준 미정','데이터':'最大 20%', '근거':'참고'}])
        display = td.judgment(source).data
        self.assertEqual(display.iloc[0]['판정'],'판정 보류 · 기준 필요')
        self.assertIn('지속시간', display.iloc[0]['추가로 필요한 기준·자료'])
        self.assertEqual(source.iloc[0]['판정'],'기준 미정')


if __name__ == '__main__':
    unittest.main()
