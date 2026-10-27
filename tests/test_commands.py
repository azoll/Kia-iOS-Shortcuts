"""Exercise the command boundary without contacting Kia or a vehicle."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from hyundai_kia_connect_api import ClimateRequestOptions
from hyundai_kia_connect_api.exceptions import (
    AuthenticationError, AuthenticationOTPRequired, ConsentRequiredError,
)

from main import create_app


SECRET = "test-token-only-abcdefghijklmnopqrstuvwxyz0123456789"
SETTINGS = {
    "KIA_USERNAME": "example@example.invalid",
    "KIA_PASSWORD": "test-password-only",
    "KIA_PIN": "0000",
    "SECRET_KEY": SECRET,
}
HEADERS = {"Authorization": "Bearer " + SECRET}


@pytest.fixture
def setup_app():
    vehicle = SimpleNamespace(id="carnival", name="Carnival", model="Carnival HEV", year=2026)
    manager = Mock()
    manager.vehicles = {vehicle.id: vehicle}
    for method in ("start_climate", "stop_climate", "lock", "unlock"):
        getattr(manager, method).return_value = "kia-command-id"
    factory = Mock(return_value=manager)
    app = create_app(SETTINGS, factory)
    app.testing = True
    return app.test_client(), manager, factory


@pytest.mark.parametrize("path", ["/start_climate", "/stop_climate", "/lock_car", "/unlock_car"])
def test_commands_require_authentication(setup_app, path):
    client, manager, factory = setup_app
    assert client.post(path, json={}).status_code == 401
    factory.assert_not_called()
    assert not manager.mock_calls


@pytest.mark.parametrize("path", ["/auth_status", "/list_vehicles"])
def test_account_routes_require_authentication(setup_app, path):
    client, _, factory = setup_app
    assert client.get(path).status_code == 401
    factory.assert_not_called()


def test_health_does_not_initialize_kia(setup_app):
    client, _, factory = setup_app
    assert client.get("/").status_code == 200
    factory.assert_not_called()


def test_climate_uses_fahrenheit_and_explicit_duration(setup_app):
    client, manager, _ = setup_app
    response = client.post("/start_climate", headers=HEADERS,
                           json={"temperature_f": 70, "duration": 7, "defrost": True})
    assert response.status_code == 202
    vehicle_id, options = manager.start_climate.call_args.args
    assert vehicle_id == "carnival"
    assert isinstance(options, ClimateRequestOptions)
    assert (options.set_temp, options.duration, options.defrost, options.climate) == (70, 7, True, True)
    assert response.json["status"] == "submitted"
    assert response.json["command_id"] == "kia-command-id"
    assert "not yet confirmed" in response.json["message"]


@pytest.mark.parametrize("preset,temp,defrost", [("default", 72, False), ("warm", 74, True), ("cool", 68, False)])
def test_presets(setup_app, preset, temp, defrost):
    client, manager, _ = setup_app
    assert client.post("/start_climate", headers=HEADERS, json={"preset": preset}).status_code == 202
    options = manager.start_climate.call_args.args[1]
    assert (options.set_temp, options.duration, options.defrost) == (temp, 10, defrost)


def test_explicit_fields_override_preset_without_mutating_it(setup_app):
    client, manager, _ = setup_app
    body = {"preset": "warm", "temperature_f": 71, "duration": 3, "defrost": False}
    assert client.post("/start_climate", headers=HEADERS, json=body).status_code == 202
    options = manager.start_climate.call_args.args[1]
    assert (options.set_temp, options.duration, options.defrost) == (71, 3, False)
    client.post("/start_climate", headers=HEADERS, json={"preset": "warm"})
    assert manager.start_climate.call_args.args[1].set_temp == 74


@pytest.mark.parametrize("body", [
    [], None, "warm", {"preset": []}, {"preset": "hot"}, {"temperature": 72},
    {"temperature_f": True}, {"temperature_f": "72"}, {"temperature_f": 72.5},
    {"temperature_f": 61}, {"temperature_f": 83}, {"duration": 0}, {"duration": 11},
    {"duration": True}, {"duration": 2.5}, {"defrost": "false"},
])
def test_invalid_inputs_do_not_contact_kia(setup_app, body):
    client, _, factory = setup_app
    import json
    response = client.post("/start_climate", headers=HEADERS,
                           data=json.dumps(body), content_type="application/json")
    assert response.status_code == 400
    factory.assert_not_called()


@pytest.mark.parametrize("data,content_type", [("{broken", "application/json"), ("hello", "text/plain")])
def test_malformed_requests_do_not_contact_kia(setup_app, data, content_type):
    client, _, factory = setup_app
    assert client.post("/start_climate", headers=HEADERS, data=data,
                       content_type=content_type).status_code == 400
    factory.assert_not_called()


@pytest.mark.parametrize("path,method,command", [
    ("/lock_car", "lock", "lock"), ("/unlock_car", "unlock", "unlock"),
    ("/stop_climate", "stop_climate", "stop_climate"),
])
def test_simple_commands_report_submission(setup_app, path, method, command):
    client, manager, _ = setup_app
    response = client.post(path, headers=HEADERS, json={})
    assert response.status_code == 202
    getattr(manager, method).assert_called_once_with("carnival")
    assert response.json["command"] == command
    assert response.json["status"] == "submitted"
    assert client.get(path, headers=HEADERS).status_code == 405


def test_upstream_raw_auth_header_and_empty_climate_body_remain_supported(setup_app):
    client, manager, _ = setup_app
    assert client.post("/start_climate", headers={"Authorization": SECRET}).status_code == 202
    assert manager.start_climate.call_args.args[1].set_temp == 72


def test_multiple_vehicles_require_an_explicit_choice(setup_app):
    client, manager, _ = setup_app
    manager.vehicles["other-car"] = SimpleNamespace(id="other-car")
    assert client.post("/unlock_car", headers=HEADERS).status_code == 409
    manager.unlock.assert_not_called()


def test_configured_vehicle_is_selected_from_multi_vehicle_account(setup_app):
    _, manager, factory = setup_app
    manager.vehicles["other-car"] = SimpleNamespace(id="other-car")
    client = create_app(SETTINGS | {"VEHICLE_ID": "carnival"}, factory).test_client()
    assert client.post("/unlock_car", headers=HEADERS).status_code == 202
    manager.unlock.assert_called_once_with("carnival")


def test_unknown_configured_vehicle_cannot_receive_commands(setup_app):
    _, manager, factory = setup_app
    client = create_app(SETTINGS | {"VEHICLE_ID": "wrong"}, factory).test_client()
    assert client.post("/unlock_car", headers=HEADERS).status_code == 409
    manager.unlock.assert_not_called()


@pytest.mark.parametrize("error,status", [(AuthenticationError("SECRET DETAIL"), 503),
                                         (ValueError("SECRET DETAIL"), 502),
                                         (RuntimeError("SECRET DETAIL"), 502)])
def test_upstream_errors_do_not_leak_details(setup_app, error, status):
    client, manager, _ = setup_app
    manager.check_and_refresh_token.side_effect = error
    response = client.post("/unlock_car", headers=HEADERS)
    assert response.status_code == status
    assert "SECRET DETAIL" not in response.get_data(as_text=True)
    manager.unlock.assert_not_called()


def test_unknown_result_is_not_claimed_as_success(setup_app):
    client, manager, _ = setup_app
    manager.unlock.return_value = None
    response = client.post("/unlock_car", headers=HEADERS)
    assert response.status_code == 502
    assert "unknown" in response.json["error"]


def test_missing_or_short_secret_fails_closed(setup_app):
    _, _, factory = setup_app
    client = create_app(SETTINGS | {"SECRET_KEY": "short"}, factory).test_client()
    assert client.post("/unlock_car", headers=HEADERS).status_code == 503
    factory.assert_not_called()


def test_missing_kia_settings_do_not_initialize_manager(setup_app):
    _, _, factory = setup_app
    client = create_app({"SECRET_KEY": SECRET}, factory).test_client()
    response = client.post("/unlock_car", headers=HEADERS)
    assert response.status_code == 503
    assert response.json["error_code"] == "service_configuration_missing"
    factory.assert_not_called()


@pytest.mark.parametrize("exception,code", [
    (AuthenticationOTPRequired, "kia_otp_required"),
    (ConsentRequiredError, "kia_consent_required"),
    (AuthenticationError, "kia_authentication_failed"),
])
def test_kia_authentication_failure_categories_are_safe(setup_app, exception, code):
    client, manager, _ = setup_app
    manager.check_and_refresh_token.side_effect = exception("PRIVATE_SESSION_DETAIL")
    response = client.get("/auth_status", headers=HEADERS)
    assert response.status_code == 503
    assert response.json["error_code"] == code
    assert "PRIVATE_SESSION_DETAIL" not in response.get_data(as_text=True)
    manager.start_climate.assert_not_called()
    manager.lock.assert_not_called()
    manager.unlock.assert_not_called()


def test_simple_commands_reject_extra_fields(setup_app):
    client, _, factory = setup_app
    assert client.post("/unlock_car", headers=HEADERS, json={"vehicle_id": "other"}).status_code == 400
    factory.assert_not_called()


def test_list_vehicles_uses_authenticated_account(setup_app):
    client, manager, _ = setup_app
    response = client.get("/list_vehicles", headers=HEADERS)
    assert response.status_code == 200
    assert response.json["vehicles"][0]["id"] == "carnival"
    manager.check_and_refresh_token.assert_called_once()
