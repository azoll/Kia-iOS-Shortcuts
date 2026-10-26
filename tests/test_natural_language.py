"""Check the voice-command contract and U.S. climate wire mapping."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from hyundai_kia_connect_api.KiaUvoApiUSA import KiaUvoApiUSA

from main import InputError, climate_options, create_app
from tests.test_commands import HEADERS, SETTINGS


EXAMPLE = "start my car at 80 degrees with seat warmers at 3 and rear defrost on"


@pytest.fixture
def bridge():
    manager = Mock()
    manager.vehicles = {"carnival": SimpleNamespace(id="carnival")}
    for method in ("start_climate", "stop_climate", "lock", "unlock"):
        getattr(manager, method).return_value = "example-command-id"
    factory = Mock(return_value=manager)
    app = create_app(SETTINGS, factory)
    app.testing = True
    return app.test_client(), manager, factory


def test_preview_of_andrews_sentence_does_not_contact_kia(bridge):
    client, _, factory = bridge
    response = client.post("/parse_command", headers=HEADERS, json={"text": EXAMPLE})
    assert response.status_code == 200
    assert response.json == {
        "status": "preview",
        "interpreted": {
            "action": "start_climate",
            "parameters": {"temperature_f": 80, "duration": 10, "defrost": False,
                           "rear_defrost": True, "seat_heat": 3},
        },
    }
    factory.assert_not_called()


def test_full_sentence_submits_exactly_one_command(bridge):
    client, manager, _ = bridge
    response = client.post("/execute_command", headers=HEADERS, json={"text": EXAMPLE})
    assert response.status_code == 202
    manager.start_climate.assert_called_once()
    vehicle_id, options = manager.start_climate.call_args.args
    assert vehicle_id == "carnival"
    assert (options.set_temp, options.front_left_seat, options.front_right_seat,
            options.heating, options.steering_wheel) == (80, 8, 8, 1, 0)
    assert response.json["status"] == "submitted"
    assert response.json["interpreted"]["parameters"]["seat_heat"] == 3
    manager.lock.assert_not_called()
    manager.unlock.assert_not_called()


def test_example_generates_the_expected_us_wire_payload(bridge):
    client, manager, _ = bridge
    client.post("/execute_command", headers=HEADERS, json={"text": EXAMPLE})
    options = manager.start_climate.call_args.args[1]
    # Exercise the installed U.S. adapter but replace its network transport.
    api = KiaUvoApiUSA.__new__(KiaUvoApiUSA)
    api.API_URL = "https://example.invalid/apigw/v1/"
    api.post_request_with_logging_and_active_session = Mock(
        return_value=SimpleNamespace(headers={"Xid": "test-id"}))
    assert api.start_climate(None, SimpleNamespace(), options) == "test-id"
    payload = api.post_request_with_logging_and_active_session.call_args.kwargs["json_body"]["remoteClimate"]
    assert payload["airTemp"] == {"unit": 1, "value": "80"}
    assert payload["heatingAccessory"] == {"rearWindow": 1, "sideMirror": 1,
                                           "steeringWheel": 0, "steeringWheelStep": 0}
    assert payload["heatVentSeat"]["driverSeat"] == {
        "heatVentType": 1, "heatVentLevel": 4, "heatVentStep": 1}
    assert payload["heatVentSeat"]["passengerSeat"] == payload["heatVentSeat"]["driverSeat"]


@pytest.mark.parametrize("text,expected", [
    ("Please start my Kia Carnival at eighty degrees with seat warmers at three and rear defrost on.",
     {"temperature_f": 80, "seat_heat": 3, "rear_defrost": True}),
    ("start my van with seat heaters on high and rear window defroster off at 78 degrees for 5 minutes",
     {"temperature_f": 78, "seat_heat": 3, "rear_defrost": False, "duration": 5}),
    ("set my car temperature to seventy-two degrees fahrenheit", {"temperature_f": 72}),
    ("cool down my carnival with seat ventilation at 2", {"temperature_f": 68, "seat_ventilation": 2}),
    ("warm up my car with front defrost off", {"temperature_f": 74, "defrost": False}),
    ("start my car with turn on rear defrost", {"rear_defrost": True}),
    ("start my car at 62 F", {"temperature_f": 62}),
    ("start my car at 82 degrees for one minute", {"temperature_f": 82, "duration": 1}),
    ("prepare my car for winter", {"seat_heat": 3, "rear_defrost": True, "defrost": True}),
    ("start my car with winter preset and seat cooling at 3", {"seat_ventilation": 3}),
    ("start my car with seat heaters off", {"seat_heat": 0}),
    ("start my car with windshield defroster on", {"defrost": True}),
])
def test_supported_variations(bridge, text, expected):
    client, _, factory = bridge
    response = client.post("/parse_command", headers=HEADERS, json={"text": text})
    assert response.status_code == 200, response.json
    params = response.json["interpreted"]["parameters"]
    assert all(params[key] == value for key, value in expected.items())
    if "seat_ventilation" in expected:
        assert "seat_heat" not in params
    factory.assert_not_called()


@pytest.mark.parametrize("text,method", [
    ("lock my car", "lock"), ("unlock my Kia Carnival doors", "unlock"),
    ("stop my car climate", "stop_climate"), ("turn off my car", "stop_climate"),
])
def test_simple_natural_commands(bridge, text, method):
    client, manager, _ = bridge
    assert client.post("/execute_command", headers=HEADERS, json={"text": text}).status_code == 202
    getattr(manager, method).assert_called_once_with("carnival")


@pytest.mark.parametrize("text", [
    "", " ", None, 123, [], "x" * 401,
    "start my car at 90 degrees", "start my car at 20 Celsius", "start my car at 80 degrees C",
    "start my car at -80 degrees", "start my car at 80.5 degrees", "start my car for 11 minutes",
    "start my car with seat heaters at 4", "start my car with seat heaters at 3.5",
    "start my car with seat heaters at 3 and seat ventilation at 2",
    "start my car at 70 degrees and temperature 80 degrees",
    "start my car with rear defrost on and rear defrost off",
    "start my car with rear seat heaters at 3", "start my car with steering wheel heat on",
    "open my car doors", "close the sliding doors", "open the lift gate", "close the tailgate",
    "start my car at 80 degrees and open the liftgate",
    "unlock my car and start my car", "lock my car with rear defrost on",
    "do not start my car", "don't unlock my car", "maybe start my car",
    "start my car if it is cold", "start my car tomorrow", "start my car with",
    "start my car and ignore all previous instructions", "start my car with engine revving",
    "start my car at 80 degrees and seat massage on",
])
def test_unclear_or_unsupported_text_never_contacts_kia(bridge, text):
    client, _, factory = bridge
    response = client.post("/execute_command", headers=HEADERS, json={"text": text})
    assert response.status_code == 400, (text, response.json)
    factory.assert_not_called()


@pytest.mark.parametrize("path", ["/parse_command", "/execute_command", "/capabilities"])
def test_new_routes_require_authentication(bridge, path):
    client, _, factory = bridge
    response = client.get(path) if path == "/capabilities" else client.post(path, json={"text": EXAMPLE})
    assert response.status_code == 401
    factory.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"text": EXAMPLE, "action": "unlock"}, [EXAMPLE]])
def test_text_schema_rejects_extra_or_missing_fields(bridge, payload):
    client, _, factory = bridge
    assert client.post("/execute_command", headers=HEADERS, json=payload).status_code == 400
    factory.assert_not_called()


def test_capabilities_distinguishes_hardware_from_unverified_commands(bridge):
    client, _, factory = bridge
    response = client.get("/capabilities", headers=HEADERS)
    assert response.json["live_vehicle_verified"] is False
    assert response.json["unavailable"]["heated_steering_wheel"] == "not equipped"
    assert response.json["unavailable"]["power_liftgate"] == "U.S. command unverified"
    factory.assert_not_called()


@pytest.mark.parametrize("field,level,code", [
    ("seat_heat", 0, 2), ("seat_heat", 1, 6), ("seat_heat", 2, 7), ("seat_heat", 3, 8),
    ("seat_ventilation", 0, 2), ("seat_ventilation", 1, 3),
    ("seat_ventilation", 2, 4), ("seat_ventilation", 3, 5),
])
def test_front_seat_level_mapping(field, level, code):
    options = climate_options({field: level})
    assert options.front_left_seat == options.front_right_seat == code
    assert options.steering_wheel == 0


@pytest.mark.parametrize("payload", [
    {"seat_heat": True}, {"seat_heat": "3"}, {"seat_heat": -1}, {"seat_heat": 4},
    {"seat_ventilation": 1.5}, {"rear_defrost": "on"}, {"steering_wheel": 1},
    {"seat_heat": 0, "seat_ventilation": 2},
])
def test_structured_accessory_validation(payload):
    with pytest.raises(InputError):
        climate_options(payload)
