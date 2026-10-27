"""Check diagnostics without releasing tokens or issuing vehicle commands."""

from contextlib import contextmanager
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlparse

import pytest


@pytest.fixture
def checker(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts" / "check-cloud-run.py"
    spec = importlib.util.spec_from_file_location("private_checker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    service = {"status": {"url": "https://example.run.app"}, "spec": {"template": {
        "spec": {"containers": [{"env": [{"name": "SECRET_KEY", "valueFrom": {
            "secretKeyRef": {"name": "kia-bridge-token", "key": "7"}}}]}]}}}}
    calls = []

    def gcloud(*args):
        calls.append(args)
        if args[:3] == ("run", "services", "describe"):
            return json.dumps(service)
        if args[:3] == ("secrets", "versions", "access"):
            assert args[3] == "7"
            return "PRIVATE_BRIDGE_TOKEN"
        return "PRIVATE_GOOGLE_TOKEN"

    monkeypatch.setattr(module, "gcloud", gcloud)
    return module, service, calls


@contextmanager
def response(body):
    stream = BytesIO(json.dumps(body).encode())
    stream.status = 200
    yield stream


def test_default_checks_do_not_attempt_kia_login_or_print_tokens(checker, monkeypatch, capsys):
    module, _, _ = checker
    paths = []

    def open_request(req, timeout):
        path = urlparse(req.full_url).path
        paths.append(path)
        assert req.get_header("X-serverless-authorization") == "Bearer PRIVATE_GOOGLE_TOKEN"
        if path == "/capabilities":
            assert req.get_header("Authorization") is None
            raise HTTPError(req.full_url, 401, "Unauthorized", {}, BytesIO(b'{}'))
        assert req.get_header("Authorization") == "Bearer PRIVATE_BRIDGE_TOKEN"
        return response({"status": "ok"})

    monkeypatch.setattr(module, "urlopen", open_request)
    monkeypatch.setattr(sys, "argv", ["checker", "personal-project"])
    module.main()
    output = capsys.readouterr().out
    assert paths == ["/", "/capabilities", "/parse_command"]
    assert "PRIVATE_" not in output


def test_login_diagnostic_prints_only_allowlisted_code(checker, monkeypatch, capsys):
    module, _, _ = checker
    paths = []

    def open_request(req, timeout):
        path = urlparse(req.full_url).path
        paths.append(path)
        if path == "/capabilities":
            raise HTTPError(req.full_url, 401, "Unauthorized", {}, BytesIO(b'{}'))
        if path == "/auth_status":
            body = {"error_code": "kia_otp_required", "error": "PRIVATE_SESSION_DETAILS"}
            raise HTTPError(req.full_url, 503, "PRIVATE_HEADER", {}, BytesIO(json.dumps(body).encode()))
        return response({"status": "ok"})

    monkeypatch.setattr(module, "urlopen", open_request)
    monkeypatch.setattr(sys, "argv", ["checker", "personal-project", "--kia-login"])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 1
    output = capsys.readouterr().out
    assert "kia_otp_required" in output
    assert "PRIVATE_" not in output
    assert paths == ["/", "/capabilities", "/parse_command", "/auth_status"]


def test_unexpected_host_stops_before_reading_or_sending_tokens(checker, monkeypatch):
    module, service, calls = checker
    service["status"]["url"] = "https://example.invalid"
    monkeypatch.setattr(sys, "argv", ["checker", "personal-project"])
    with pytest.raises(SystemExit, match="Unexpected service URL"):
        module.main()
    assert len(calls) == 1
    assert calls[0][:3] == ("run", "services", "describe")
