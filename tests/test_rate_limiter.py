import pytest

from src.core.rate_limiter import call_with_retry, TokenBucketLimiter


def test_call_with_retry_retries_on_ab1021_and_succeeds():
    calls = {'count': 0}

    def stub_api(*args, **kwargs):
        calls['count'] += 1
        if calls['count'] < 2:
            return {
                'status': False,
                'message': 'AB1021 Too many requests',
                'errorcode': 'AB1021'
            }
        return {'status': True, 'data': []}

    result = call_with_retry(stub_api, base_delay=0.01, max_retries=3)

    assert result == {'status': True, 'data': []}
    assert calls['count'] == 2


def test_call_with_retry_raises_after_max_retries_on_ab1021():
    calls = {'count': 0}

    def stub_api(*args, **kwargs):
        calls['count'] += 1
        return {
            'status': False,
            'message': 'AB1021 Too many requests',
            'errorcode': 'AB1021'
        }

    with pytest.raises(RuntimeError):
        call_with_retry(stub_api, base_delay=0.01, max_retries=2)

    assert calls['count'] == 3


def test_call_with_retry_raises_when_limiter_acquire_fails():
    class FailingLimiter:
        def acquire(self, timeout=30):
            return False

    with pytest.raises(RuntimeError, match='Could not acquire slot'):
        call_with_retry(lambda: {'status': True, 'data': []}, limiter=FailingLimiter(), max_retries=1, base_delay=0.01)
