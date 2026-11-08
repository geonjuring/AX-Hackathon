"""Shared visitor-facing formulas and fictional examples for management reports."""
from html import escape

HEADERS = ('지표', '계산식·설명', '예시 (설명용 가상 값)')
ROWS = (
    ('전체·A조·B조 생산량', '해당 범위의 생산실적 합계. A조·B조는 각 조의 실적을 따로 합산합니다.', 'A조 6,000kg + B조 4,000kg = 전체 10,000kg'),
    ('평균 LOT SIZE', '생산량 ÷ 생산 LOT 건수. 같은 날짜·호기의 동일 LOT는 중복을 제거합니다.', '10,000kg ÷ 5건 = 2,000kg/LOT'),
    ('통합 LOT SIZE', '생산량 ÷ (통합 그룹 수 + 단독 LOT 수)', '10,000kg ÷ (통합 2묶음 + 단독 2묶음) = 2,500kg/묶음'),
    ('가동률', '가동 시간 합계 ÷ 기준 시간 합계 × 100. 기준 시간은 날짜별로 가동이 확인된 호기당 24시간입니다.', '2개 호기의 하루 기준 시간 48시간 중 가동 36시간 → 75%'),
    ('생산 라인 비율', '생산실적이 있는 호기 수 ÷ 선택한 호기 수 × 100', '선택한 10개 호기 중 8개에서 생산 → 80%'),
    ('금월 가동일', '월초부터 기준일까지 생산량이 발생한 날짜 수', '생산실적이 있는 날짜가 20일 → 20일'),
    ('금월 일평균', '금월 누적 생산량 ÷ 금월 가동일', '100,000kg ÷ 20일 = 5,000kg/일'),
    ('인당 생산량', '생산량 ÷ 누적 적용 인원. 적용 인원은 생산일보의 총원에서 결원을 뺀 인원입니다.', '10,000kg ÷ 50명·교대 = 200kg/명·교대'),
    ('전체 사용 전력량', '센서 측정 기준: 해당 기간 사용량 합계. 청구 기준은 아래 방식으로 추정 배분합니다.', '하루 사용량 300kWh + 400kWh = 700kWh'),
    ('청구 기준 전력량', '보정계수 = 월 청구 전력량 ÷ 월 센서 측정량. 기간 센서 측정량 × 보정계수', '월 청구량 11,000kWh ÷ 월 측정량 10,000kWh = 1.1 → 기간 측정량 500kWh × 1.1 = 550kWh'),
    ('압출기 전력량', '선택한 호기의 압출기 사용 전력량 합계. 청구 기준이면 같은 보정계수를 적용합니다.', '1호기 200kWh + 2호기 300kWh = 500kWh'),
)


def render_markdown():
    lines = ['| ' + ' | '.join(HEADERS) + ' |', '|---|---|---|']
    lines.extend('| ' + ' | '.join(row) + ' |' for row in ROWS)
    return '\n'.join(lines)


def render_html():
    def cell(tag, value):
        return f'<{tag} style="text-align:left;vertical-align:top">{escape(value)}</{tag}>'
    header = '<tr>' + ''.join(cell('th', value) for value in HEADERS) + '</tr>'
    body = ''.join('<tr>' + ''.join(cell('td', value) for value in row) + '</tr>' for row in ROWS)
    return '<table class="calculation-basis"><thead>' + header + '</thead><tbody>' + body + '</tbody></table>'
