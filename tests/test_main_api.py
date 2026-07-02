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


@pytest.fixture

def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client
