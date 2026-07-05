from datetime import datetime

from main import app


def test_intel_logs_route(tmp_path, monkeypatch):
    log_dir = tmp_path / 'logs'
    log_dir.mkdir(parents=True)
    log_file = log_dir / 'brain_service.log'
    log_file.write_text('2026-07-01 Test log entry\n', encoding='utf-8')

    monkeypatch.setattr('main.os.path.dirname', lambda _: str(tmp_path))

    app.config['TESTING'] = True
    with app.test_client() as client:
        response = client.get('/api/logs?service=brain_service')
        assert response.status_code == 200
        data = response.get_json()
        assert 'lines' in data
        assert data['count'] == 1
        assert data['lines'][0]['text'] == '2026-07-01 Test log entry'
