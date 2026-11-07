"""Display only: round to two decimals without changing source values."""
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from numbers import Real, Integral
import math
import re
import pandas as pd


def number(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return '—'
    if isinstance(value, datetime):
        return value.isoformat(sep=' ', timespec='milliseconds')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, Real):
        if not math.isfinite(value):
            return '—'
        if isinstance(value, Integral):
            return f'{int(value):,}'
        decimal = Decimal(str(value))
        with localcontext() as ctx:
            ctx.prec = max(28, decimal.adjusted() + 4)
            text = format(decimal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        if Decimal(text) == 0:
            text = '0'
        whole, dot, fraction = text.partition('.')
        return ('-' if text.startswith('-') else '') + f'{abs(int(whole)):,}' + (dot + fraction if dot else '')
    return str(value)


_DECIMAL = re.compile(r'(?<![\w.])([+-]?\d[\d,]*\.\d+)(?![\w.]|\d)')


def text(value):
    if not isinstance(value, str):
        return number(value)
    def trim(match):
        return number(float(match.group(1).replace(',', '')))
    return _DECIMAL.sub(trim, value)
