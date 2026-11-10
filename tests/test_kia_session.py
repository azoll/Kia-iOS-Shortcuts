"""Verify private enrollment and reuse of remembered Kia sessions."""

from datetime import datetime, timedelta, UTC
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from hyundai_kia_connect_api import VehicleManager
from hyundai_kia_connect_api.ApiImpl import OTPRequest
from hyundai_kia_connect_api.KiaUvoApiUSA import KiaUvoApiUSA
from hyundai_kia_connect_api.Token import Token
from hyundai_kia_connect_api.const import OTP_NOTIFY_TYPE
from hyundai_kia_connect_api.exceptions import AuthenticationOTPRequired

from kia_session import SessionConfigurationError, load_remembered_session, save_remembered_session
from main import create_app
from tests.test_commands import HEADERS, SETTINGS


DEVICE = "11111111-2222-3333-4444-555555555555"
SESSION = {"version": 1, "username": SETTINGS["KIA_USERNAME"],
           "device_id": DEVICE, "refresh_token": "PRIVATE_REMEMBER_TOKEN"}


def test_saved_session_excludes_password_pin_access_token_and_other_fields():
    token = Token(username=SETTINGS["KIA_USERNAME"], password="PRIVATE_PASSWORD",
        pin="PRIVATE_PIN", access_token="PRIVATE_SESSION_ID", refresh_token=SESSION["refresh_token"],
        device_id=DEVICE, stamp="PRIVATE_STAMP")
    serialized = save_remembered_session(token)
    assert json.loads(serialized) == SESSION
    assert all(secret not in serialized for secret in
               (token.password, token.pin, token.access_token, token.stamp))


def test_restored_session_uses_current_credentials_and_forces_refresh():
    token = load_remembered_session(json.dumps(SESSION), SETTINGS["KIA_USERNAME"],
                                    "CURRENT_PASSWORD", "0007")
    assert token.password == "CURRENT_PASSWORD" and token.pin == "0007"
    assert token.access_token is None
    assert token.device_id == DEVICE
    assert token.refresh_token == SESSION["refresh_token"]
    assert token.valid_until < datetime.now(UTC)


def test_pinned_us_adapter_refresh_sends_remember_token_and_original_device():
    token = load_remembered_session(json.dumps(SESSION), SETTINGS["KIA_USERNAME"],
                                    "CURRENT_PASSWORD", "0007")
    api = KiaUvoApiUSA(3, 1, "en")
    api.session = Mock()
    api.session.post.return_value = SimpleNamespace(
        headers={"sid": "PRIVATE_NEW_SESSION"}, text="not logged by this test",
        json=lambda: {"status": {"statusCode": 0}})
    refreshed = api.refresh_access_token(token)
    request = api.session.post.call_args.kwargs
    assert request["headers"]["rmtoken"] == SESSION["refresh_token"]
    assert request["headers"]["deviceid"] == DEVICE
    assert request["json"]["deviceKey"] == DEVICE
    assert refreshed.refresh_token == SESSION["refresh_token"]
    assert refreshed.device_id == DEVICE


@pytest.mark.parametrize("raw", [
    "not json", "[]", "{}", "x" * 16385,
    json.dumps(SESSION | {"username": "different@example.invalid"}),
    json.dumps(SESSION | {"password": "PRIVATE_PASSWORD"}),
    json.dumps(SESSION | {"version": True}),
    json.dumps(SESSION | {"device_id": "invalid"}),
    json.dumps(SESSION | {"refresh_token": None}),
])
def test_bad_session_fails_closed_before_kia_but_does_not_break_preview(raw):
    factory = Mock()
    client = create_app(SETTINGS | {"KIA_SESSION": raw}, factory).test_client()
    assert client.post("/parse_command", headers=HEADERS,
                       json={"text": "start my car at 80 degrees"}).status_code == 200
    response = client.get("/auth_status", headers=HEADERS)
    assert response.status_code == 503
    assert response.json["error_code"] == "kia_session_invalid"
    assert raw not in response.get_data(as_text=True)
    factory.assert_not_called()


def test_two_cold_starts_refresh_from_same_remember_token_without_password_login():
    apis = []

    def factory(**kwargs):
        manager = VehicleManager(**kwargs)
        api = Mock(supports_window_control=False, supports_valet_mode=False, supports_svm=False)
        api.get_vehicles.return_value = [SimpleNamespace(id="carnival")]

        def refresh(token):
            assert api.device_id == DEVICE
            assert token.refresh_token == SESSION["refresh_token"]
            return Token(username=token.username, password=token.password, pin=token.pin,
                device_id=DEVICE, refresh_token=token.refresh_token, access_token="NEW_PRIVATE_SESSION",
                valid_until=datetime.now(UTC) + timedelta(hours=23))

        api.refresh_access_token.side_effect = refresh
        manager.api = api
        apis.append(api)
        return manager

    for _ in range(2):
        client = create_app(SETTINGS | {"KIA_SESSION": json.dumps(SESSION)}, factory).test_client()
        assert client.get("/auth_status", headers=HEADERS).status_code == 200
    assert len(apis) == 2
    for api in apis:
        api.refresh_access_token.assert_called_once()
        api.login.assert_not_called()
        api.start_climate.assert_not_called()
        api.lock_action.assert_not_called()


def test_expired_remembered_session_reports_otp_requirement_without_commands():
    manager = Mock()
    manager.check_and_refresh_token.side_effect = AuthenticationOTPRequired("PRIVATE_RESPONSE")
    client = create_app(SETTINGS | {"KIA_SESSION": json.dumps(SESSION)},
                        Mock(return_value=manager)).test_client()
    response = client.get("/auth_status", headers=HEADERS)
    assert response.json["error_code"] == "kia_otp_required"
    assert "PRIVATE_RESPONSE" not in response.get_data(as_text=True)
    manager.start_climate.assert_not_called()


@pytest.fixture
def enrollment():
    path = Path(__file__).resolve().parents[1] / "scripts" / "enroll-kia-session.py"
    spec = importlib.util.spec_from_file_location("enrollment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enrollment_asks_for_method_then_verifies_code_without_displaying_it(enrollment, capsys):
    manager = Mock()
    manager.login.return_value = OTPRequest("private-request", "private-key", True, True,
                                           "private-email", "private-phone")
    choose = Mock(return_value="sms")
    code = Mock(return_value="001234")
    enrollment.authenticate(manager, choose=choose, read_code=code)
    choose.assert_called_once()
    manager.send_otp.assert_called_once_with(OTP_NOTIFY_TYPE.SMS)
    manager.verify_otp_and_complete_login.assert_called_once_with("001234")
    output = capsys.readouterr().out
    assert all(value not in output for value in
               ("001234", "private-request", "private-key", "private-email", "private-phone"))
    manager.start_climate.assert_not_called()
    manager.lock.assert_not_called()


def test_only_available_method_is_used_and_invalid_choice_does_not_send_code(enrollment):
    manager = Mock()
    manager.login.return_value = OTPRequest("request", "key", True, False, None, None)
    choose = Mock()
    enrollment.authenticate(manager, choose=choose, read_code=Mock(return_value="123456"))
    choose.assert_not_called()
    manager.send_otp.assert_called_once_with(OTP_NOTIFY_TYPE.EMAIL)
    manager.reset_mock()
    manager.login.return_value = OTPRequest("request", "key", True, True, None, None)
    with pytest.raises(SystemExit, match="No code was requested"):
        enrollment.authenticate(manager, choose=Mock(return_value="fax"))
    manager.send_otp.assert_not_called()


def test_session_is_sent_to_secret_manager_only_through_stdin(enrollment, monkeypatch):
    cloud = Mock(return_value="")
    monkeypatch.setattr(enrollment, "gcloud", cloud)
    serialized = json.dumps(SESSION)
    enrollment.persist_session("personal-project", serialized)
    create = cloud.call_args_list[1]
    assert create.args[:3] == ("secrets", "create", "kia-session")
    assert create.kwargs["input_data"] == serialized.encode()
    assert all(serialized not in str(call.args) for call in cloud.call_args_list)
    policy = cloud.call_args_list[2]
    assert policy.args[:3] == ("secrets", "add-iam-policy-binding", "kia-session")
    assert "--role=roles/secretmanager.secretAccessor" in policy.args


def test_deployed_password_bytes_are_not_stripped(enrollment, monkeypatch):
    refs = [{"name": name, "valueFrom": {"secretKeyRef": {"name": name, "key": "2"}}}
            for name in ("KIA_USERNAME", "KIA_PASSWORD", "KIA_PIN")]
    config = {"spec": {"template": {"spec": {"containers": [{"env": refs}]}}}}
    cloud = Mock(side_effect=[json.dumps(config), "email@example.invalid", "  PRIVATE_PASSWORD  ", "0007"])
    monkeypatch.setattr(enrollment, "gcloud", cloud)
    credentials = enrollment.deployed_credentials("personal-project")
    assert credentials["KIA_PASSWORD"] == "  PRIVATE_PASSWORD  "
    assert credentials["KIA_PIN"] == "0007"
    assert all(call.kwargs["strip"] is False for call in cloud.call_args_list[1:])
