import pytest

from main import app


def test_index_route(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b"Quant" in response.data or b"index" in response.data.lower()


def test_status_api(client):
    response = client.get('/api/status')
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, dict)
    assert 'status' in data
    assert 'system_info' in data
    assert data['system_info']['engine_version'] == '1.1.0'

def test_operator_dto_system_info(client):
    response = client.get('/api/operator')
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, dict)
    assert 'system_info' in data
    assert data['system_info']['engine_version'] == '1.1.0'

def test_notification_priority_mapping():
    from src.core.telemetry_aggregator import get_notification_priority
    
    # Critical
    assert get_notification_priority("BUY_EXECUTED", "") == "CRITICAL"
    assert get_notification_priority("", "Stop Loss Hit") == "CRITICAL"
    assert get_notification_priority("FEED_OFFLINE", "") == "CRITICAL"
    
    # High
    assert get_notification_priority("BRAIN_RESTARTED", "") == "HIGH"
    assert get_notification_priority("", "Research Completed successfully") == "HIGH"
    
    # Normal
    assert get_notification_priority("DAILY_SUMMARY_READY", "") == "NORMAL"
    assert get_notification_priority("", "Audit Passed") == "NORMAL"
    
    # Low / Fallback
    assert get_notification_priority("HEARTBEAT", "") == "LOW"
    assert get_notification_priority("UNKNOWN_EVENT", "Routine check completed") == "LOW"

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client
