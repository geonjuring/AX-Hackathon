"""Bounded server-side calls to the deployed numerical AIStream service."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import math
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

BASE_URL = 'https://aiopen-serving.jntp-ax.or.kr/jntp-cpu/SV-32e32cdb'
SCOPE = {'line': '06', 'grade': 'SR-0310FMU', 'color': 'NP'}
SCHEMA = 'slp-equipment-pattern-v1'
MODEL = '0.1.0-pilot'
REFERENCE = '2026-10-01T00:00:00+09:00'
MAX_BYTES = 2 * 1024 * 1024


class AIStreamError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    url: str = BASE_URL
    timeout: float = 45

    @classmethod
    def from_env(cls):
        url = os.environ.get('AISTREAM_BASE_URL', '').strip().rstrip('/') or BASE_URL
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise AIStreamError('AIStream 주소는 인증정보·쿼리가 없는 HTTPS 서비스 기본 주소로 설정하세요.')
        try:
            timeout = float(os.environ.get('AISTREAM_TIMEOUT_SECONDS', '') or 45)
        except ValueError as exc:
            raise AIStreamError('AIStream 제한시간은 3~120초의 숫자로 설정하세요.') from exc
        if not math.isfinite(timeout) or not 3 <= timeout <= 120:
            raise AIStreamError('AIStream 제한시간은 3~120초로 설정하세요.')
        return cls(url, timeout)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def encoded(payload):
    return json.dumps(payload, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _time(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone missing')
    return parsed


def validate(data, payload):
    """Reject a mismatched model, omitted windows, and inconsistent decisions."""
    try:
        if (data['schema_version'] != SCHEMA or data['model_version'] != MODEL
                or data['scope'] != SCOPE or _time(data['as_of']) != _time(payload['as_of'])
                or _time(data['reference_available_after']) != _time(REFERENCE)):
            raise ValueError('model/context mismatch')
        threshold = data['candidate_threshold']
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
            raise ValueError('invalid threshold')
        expected = set()
        for r in payload['records']:
            ts = _time(r['ts'])
            start = ts.replace(minute=ts.minute // 10 * 10, second=0, microsecond=0)
            expected.add((r['lot_no'], start))
        actual, evaluated, held = set(), 0, 0
        for row in data['results']:
            if any(row[k] != v for k, v in SCOPE.items()):
                raise ValueError('result scope mismatch')
            key = (row['lot_no'], _time(row['window_start']))
            if key in actual or key not in expected:
                raise ValueError('unexpected/duplicate window')
            actual.add(key)
            if (type(row['records']) is not int or row['records'] < 1
                    or _time(row['window_end'])-key[1] != timedelta(minutes=10)
                    or not isinstance(row['reasons'], list)
                    or not all(isinstance(x, str) for x in row['reasons'])
                    or not isinstance(row['related_measurements'], list)):
                raise ValueError('invalid window fields')
            for measurement in row['related_measurements']:
                if not isinstance(measurement['label'], str) or not isinstance(measurement['direction'], str):
                    raise ValueError('invalid measurement label')
                for field in ('observed', 'reference_median', 'reference_q05', 'reference_q95'):
                    value = measurement[field]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ValueError('invalid measurement')
            status, candidate = row['status'], row['candidate']
            if status == '평가 보류':
                held += 1
                if candidate is not None or row['anomaly_score'] is not None:
                    raise ValueError('withheld decision')
            elif status in ('패턴 이상 후보', '참고 패턴 범위'):
                evaluated += 1
                if type(candidate) is not bool or candidate != (status == '패턴 이상 후보'):
                    raise ValueError('decision mismatch')
                for field in ('anomaly_score', 'reference_percentile'):
                    value = row[field]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ValueError('invalid score')
                if candidate != (row['anomaly_score'] > threshold):
                    raise ValueError('threshold mismatch')
                if not 0 <= row['reference_percentile'] <= 100 or _time(row['window_end']) > _time(payload['as_of']):
                    raise ValueError('invalid evaluated interval')
            else:
                raise ValueError('unknown status')
        quality = data['data_quality']
        if (actual != expected or quality['input_records'] != len(payload['records'])
                or quality['evaluated_windows'] != evaluated or quality['withheld_windows'] != held
                or quality['total_windows'] != len(actual)):
            raise ValueError('incomplete results')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise AIStreamError('AIStream 응답의 모델·분석조건·구간 수가 요청과 일치하지 않습니다. 결과를 판정에 사용하지 마세요.') from exc
    return data


class Client:
    def __init__(self, config=None):
        self.config = config or Config.from_env()
        self.opener = urllib.request.build_opener(_NoRedirect())

    def predict(self, payload):
        body = encoded(payload)
        if not 1 <= len(payload['records']) <= 10000 or len(body) > MAX_BYTES:
            raise AIStreamError('AIStream 요청 크기 제한을 초과했습니다. 분석 범위를 줄여주세요.')
        request = urllib.request.Request(self.config.url + '/predict', data=body,
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
        try:
            with self.opener.open(request, timeout=self.config.timeout) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise AIStreamError('AIStream 응답이 너무 큽니다. 분석 범위를 줄여주세요.')
                data = json.loads(raw, parse_constant=lambda _: None)
        except urllib.error.HTTPError as exc:
            explanations = {413: '요청 크기 초과', 422: '입력 형식 검증 실패',
                429: '다른 분석 처리 중', 503: '서빙 준비 중 또는 일시 사용 불가',
                502: '서빙 연결 실패', 504: '서빙 응답 제한시간 초과'}
            raise AIStreamError(f'AIStream HTTP {exc.code}: {explanations.get(exc.code, "API 요청 실패")}. 배포 상태·로그를 확인하고 다시 분석하세요.') from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AIStreamError('AIStream 연결 또는 응답 시간이 초과됐습니다. 배포 상태·메모리·로그를 확인한 뒤 다시 분석하세요.') from exc
        except (ValueError, TypeError) as exc:
            raise AIStreamError('AIStream이 올바른 JSON 결과를 반환하지 않았습니다.') from exc
        return validate(data, payload)
