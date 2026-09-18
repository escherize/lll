#!/usr/bin/env python3
"""Exercise fleet isolation and lifecycle before provisioning real workers."""
import json
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from agent_dx_fleet import audit_path, connection, private_dir, private_write, public_snapshot, publish_audit, serve, stop

with tempfile.TemporaryDirectory(prefix='lll-fleet-harness-') as temporary:
    root = Path(temporary)
    worker = root / '01'
    private_dir(worker)
    assert worker.stat().st_mode & 0o777 == 0o700
    conn = worker / 'conn.txt'
    for text in ('http://127.0.0.1:1234\n', 'http://127.0.0.1:1234\nfake\n',
                 'https://hosted.invalid:1234\nfake\nFLEET\n'):
        private_write(conn, text)
        try:
            connection(conn)
        except ValueError:
            pass
        else:
            raise AssertionError('accepted partial or non-loopback connection')
    private_write(conn, 'http://127.0.0.1:1234\nthrowaway-test-token\nFLEET\n')
    assert conn.stat().st_mode & 0o777 == 0o600
    conn.chmod(0o644)
    private_write(conn, conn.read_text())
    assert conn.stat().st_mode & 0o777 == 0o600
    fake = root / 'fake-lll'
    fake.write_text('#!/usr/bin/env python3\nimport os\nfrom pathlib import Path\n'
                    'assert os.environ["LLL_URL"]=="http://127.0.0.1:1234"\n'
                    'assert os.environ["LLL_TOKEN"]=="throwaway-test-token"\n'
                    'assert os.environ["LLL_TEAM"]=="FLEET"\n'
                    'assert "LLL_POISON" not in os.environ and "XDG_POISON" not in os.environ\n'
                    'assert Path(os.environ["HOME"])==Path.cwd()/"home"\n'
                    'print("isolated wrapper: "+os.environ["LLL_TOKEN"])\n')
    fake.chmod(0o700)
    env = dict(os.environ, LLL_URL='https://hosted.invalid', LLL_TEAM='REAL',
               LLL_TOKEN='not-real-controller-token', LLL_POISON='bad', XDG_POISON='bad')
    result = subprocess.run([sys.executable, str(Path(__file__).with_name('agent_dx_fleet.py')),
                             'wrapper', str(worker), str(fake), '--help'],
                            env=env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'isolated wrapper: [REDACTED]'
    primary = audit_path(fake, worker)
    audit = json.loads(primary.read_text())
    assert audit['command'] == ['lll', '--help'] and audit['exit_code'] == 0
    assert 'throwaway-test-token' not in json.dumps(audit)
    assert not (worker / 'calls.jsonl').exists()
    (worker / 'calls.jsonl').write_text('malformed worker reconstruction')
    again = subprocess.run([sys.executable, str(Path(__file__).with_name('agent_dx_fleet.py')),
                            'wrapper', str(worker), str(fake), 'throwaway-test-token'],
                           env=env, text=True, capture_output=True, timeout=10)
    assert again.returncode == 0, again.stderr
    assert primary.stat().st_mode & 0o777 == 0o600
    assert len(primary.read_text().splitlines()) == 2
    assert 'throwaway-test-token' not in primary.read_text()
    assert publish_audit(fake, worker)
    assert (worker / 'worker-supplied-calls.jsonl').read_text() == 'malformed worker reconstruction'
    assert (worker / 'calls.jsonl').read_bytes() == primary.read_bytes()
    assert publish_audit(fake, worker)
    snapshot = {'webhooks': [{'id': 'hook', 'secret': 'throwaway-hook-secret'}]}
    assert public_snapshot(snapshot)['webhooks'][0]['secret'] == '[REDACTED]'
    assert snapshot['webhooks'][0]['secret'] == 'throwaway-hook-secret'
    run_root = root / 'fresh-run'
    def commands():
        (run_root / 'case-01-run-1').mkdir()
        yield '{"action":"provision","case":"01","run":1}\n'
    args = SimpleNamespace(root=run_root, binary=fake, commit='fixture',
                           sha256=hashlib.sha256(fake.read_bytes()).hexdigest())
    with patch('sys.stdin', commands()), patch('sys.stdout', io.StringIO()), \
         patch('agent_dx_fleet.Instance', side_effect=AssertionError('launched into reused path')):
        try:
            serve(args)
        except AssertionError as error:
            assert str(error) == 'case/run paths must be fresh', error
        else:
            raise AssertionError('accepted reused case/run path')
    exited = subprocess.Popen([sys.executable, '-c', 'pass'])
    exited.wait(timeout=5)
    exited.terminate = lambda: (_ for _ in ()).throw(AssertionError('re-signaled reaped child'))
    stop(exited)
    resistant = subprocess.Popen([sys.executable, '-c',
        'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(60)'], stdout=subprocess.PIPE, text=True)
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        assert resistant.stdout.readline().strip() == 'ready'
        stop(resistant)
        assert resistant.returncode is not None and unrelated.poll() is None
    finally:
        stop(resistant)
        stop(unrelated)
print('Fleet harness: incomplete/foreign connections refused; private files; poisoned environment cleared; audited/redacted calls; owned resistant child reaped without signaling unrelated or reaped children.')
