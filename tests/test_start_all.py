import start_all


class DummyProc:
    def __init__(self):
        self.pid = 999

    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        pass

    def kill(self):
        pass


def test_start_service_creates_process(monkeypatch):
    dummy = DummyProc()

    def fake_popen(command, env, **kwargs):
        assert command == ['python', '-c', 'print(1)']
        assert 'PYTHONPATH' in env
        assert 'stdout' in kwargs
        assert 'stderr' in kwargs
        return dummy

    monkeypatch.setattr(start_all.subprocess, 'Popen', fake_popen)

    supervisor = start_all.ProcessSupervisor([])
    supervisor.start_service('test', ['python', '-c', 'print(1)'])

    assert supervisor.processes['test'] is dummy
    assert supervisor.restart_counts['test'] == 0


def test_handle_restart_does_not_restart_after_max(monkeypatch):
    svc = {
        'name': 'svc',
        'command': ['python', '-c', 'print(1)'],
        'restart_on_failure': True,
    }
    supervisor = start_all.ProcessSupervisor([svc])
    supervisor.restart_timestamps['svc'] = [1.0, 2.0, 3.0]

    def fake_start_service(name, command):
        raise AssertionError('Should not restart after max retries')

    monkeypatch.setattr(supervisor, 'start_service', fake_start_service)
    monkeypatch.setattr(start_all.time, 'time', lambda: 3.5)

    supervisor.handle_restart(svc)
