"""Verify setup boundaries with a fake gcloud and a real terminal."""

import errno
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import time

import pytest


SETUP = Path(__file__).resolve().parents[1] / "scripts" / "setup-cloud-run.sh"
FAKE_GCLOUD = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
if args[:3] == ['config', 'get-value', 'project']:
    print('personal-project')
elif args[:3] == ['billing', 'projects', 'describe']:
    print(os.environ.get('FAKE_BILLING', 'True'))
elif args[:3] == ['iam', 'service-accounts', 'list']:
    print('existing-service-account')
elif args[:2] == ['secrets', 'list']:
    if os.environ.get('FAKE_EXISTING') == '1':
        for name in ('kia-username', 'kia-password', 'kia-pin', 'kia-bridge-token'):
            print('projects/example/secrets/' + name)
    if os.environ.get('FAKE_SESSION') == '1':
        print('projects/example/secrets/kia-session')
elif args[:3] == ['secrets', 'versions', 'list']:
    print('projects/example/secrets/example/versions/1')
elif args[:2] == ['secrets', 'create']:
    value = sys.stdin.read()
    if args[2] == 'kia-pin':
        assert value == '0007'
    assert len(value) >= (32 if args[2] == 'kia-bridge-token' else 1)
elif args[:3] == ['secrets', 'versions', 'add']:
    import hashlib
    with open(os.environ['FAKE_LOG'] + '.inputs', 'a') as log:
        log.write(json.dumps({'secret': args[3], 'sha256': hashlib.sha256(sys.stdin.buffer.read()).hexdigest()}) + '\n')
elif args[:3] == ['run', 'services', 'describe']:
    print('https://example.invalid')
'''


@pytest.fixture
def cloud_env(tmp_path):
    executable = tmp_path / "gcloud"
    executable.write_text(f"#!{sys.executable}\n" + FAKE_GCLOUD)
    executable.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    env = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}", "FAKE_LOG": str(log)}
    return env, log


def calls(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def in_terminal(env, replies, command=None):
    pid, terminal = pty.fork()
    if pid == 0:
        command = command or ["bash", str(SETUP), "personal-project"]
        os.execvpe(command[0], command, env)
    output = b""
    pending = list(replies)
    deadline = time.monotonic() + 15
    finished = False
    try:
        while time.monotonic() < deadline:
            if pending and pending[0][0].encode() in output:
                _, reply = pending.pop(0)
                os.write(terminal, reply.encode() + b"\n")
            ready, _, _ = select.select([terminal], [], [], 0.1)
            if not ready:
                continue
            try:
                chunk = os.read(terminal, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                break
            if not chunk:
                break
            output += chunk
        else:
            pytest.fail("Setup did not finish within the test deadline")
        _, status = os.waitpid(pid, 0)
        finished = True
        assert not pending, output.decode()
        return os.waitstatus_to_exitcode(status), output.decode()
    finally:
        os.close(terminal)
        if not finished:
            os.kill(pid, 9)
            os.waitpid(pid, 0)


def test_disabled_billing_stops_before_resource_changes(cloud_env):
    env, log = cloud_env
    result = subprocess.run(["bash", str(SETUP), "personal-project"],
                            env=env | {"FAKE_BILLING": "False"}, capture_output=True, text=True)
    assert result.returncode == 1
    assert "No resources were changed" in result.stderr
    assert [call[:3] for call in calls(log)] == [["billing", "projects", "describe"]]


def test_declining_target_project_makes_no_resource_changes(cloud_env):
    env, log = cloud_env
    code, output = in_terminal(env, [("Type deploy:", "no")])
    assert code == 0
    assert "Stopped without changing resources" in output
    assert [call[:3] for call in calls(log)] == [["billing", "projects", "describe"]]


def test_existing_secret_values_are_not_read_or_replaced(cloud_env):
    env, log = cloud_env
    code, output = in_terminal(env | {"FAKE_EXISTING": "1"}, [("Type deploy:", "deploy")])
    assert code == 0, output
    operations = calls(log)
    assert not any(call[:2] == ["secrets", "create"] for call in operations)
    assert not any(call[:3] in (["secrets", "versions", "access"],
                               ["secrets", "versions", "add"]) for call in operations)
    deployment = next(call for call in operations if call[:2] == ["run", "deploy"])
    assert "--no-allow-unauthenticated" in deployment
    assert "--max=1" in deployment and "--min=0" in deployment
    assert not any("allUsers" in arg for call in operations for arg in call)


def test_new_secret_entry_is_hidden_and_pin_keeps_leading_zeros(cloud_env):
    env, log = cloud_env
    username, password = "private-example@example.invalid", "private-password-for-test"
    code, output = in_terminal(env, [("Type deploy:", "deploy"),
        ("Kia Username (hidden; sent only to Google Secret Manager):", username),
        ("Kia Password (hidden; sent only to Google Secret Manager):", password),
        ("Kia PIN (hidden; sent only to Google Secret Manager):", "0007")])
    assert code == 0, output
    assert username not in output and password not in output and "0007" not in output
    creates = [call[2] for call in calls(log) if call[:2] == ["secrets", "create"]]
    assert creates == ["kia-username", "kia-password", "kia-pin", "kia-bridge-token"]


def test_credential_correction_mismatch_does_not_change_secrets(cloud_env):
    env, log = cloud_env
    command = [sys.executable, str(SETUP.with_name("update-kia-credentials.py")), "personal-project"]
    code, output = in_terminal(env, [("Kia email (visible):", "example@example.invalid"),
        ("Kia password (hidden):", "first-private-password"),
        ("Repeat Kia password (hidden):", "second-private-password")], command)
    assert code != 0
    assert "No secrets were changed" in output
    assert not log.exists()


def test_redeployment_retains_optional_remembered_session_reference(cloud_env):
    env, log = cloud_env
    code, output = in_terminal(env | {"FAKE_EXISTING": "1", "FAKE_SESSION": "1"},
                               [("Type deploy:", "deploy")])
    assert code == 0, output
    deployment = next(call for call in calls(log) if call[:2] == ["run", "deploy"])
    assert any("KIA_SESSION=kia-session:1" in arg for arg in deployment)


def test_credential_correction_never_displays_password_and_redeploys(cloud_env):
    env, log = cloud_env
    username, password = "example@example.invalid", "  exact-private-password  "
    command = [sys.executable, str(SETUP.with_name("update-kia-credentials.py")), "personal-project"]
    code, output = in_terminal(env, [("Kia email (visible):", username),
        ("Kia password (hidden):", password), ("Repeat Kia password (hidden):", password)], command)
    assert code == 0, output
    assert username in output
    assert password.strip() not in output
    operations = calls(log)
    assert not any(password in arg for call in operations for arg in call)
    written = [json.loads(line) for line in Path(str(log) + ".inputs").read_text().splitlines()]
    assert written == [
        {"secret": "kia-username", "sha256": hashlib.sha256(username.encode()).hexdigest()},
        {"secret": "kia-password", "sha256": hashlib.sha256(password.encode()).hexdigest()},
    ]
    assert any(call[:2] == ["run", "deploy"] for call in operations)
    assert not any(call[:3] == ["secrets", "versions", "access"] for call in operations)
