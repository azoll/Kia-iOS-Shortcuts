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


def test_sirius_sentence_submits_validated_climate_settings_once(bridge):
    client, manager, _ = bridge
    response = client.post('/execute_command', headers=HEADERS, json={'text':
        'Siri, tell Sirius to turn on at 80 degrees with defrost and seat warmers at 2'})
    assert response.status_code == 202, response.json
    manager.start_climate.assert_called_once()
    vehicle_id, options = manager.start_climate.call_args.args
    assert vehicle_id == 'carnival'
    assert (options.set_temp, options.defrost, options.front_left_seat,
            options.front_right_seat) == (80, True, 7, 7)
    manager.unlock.assert_not_called()
    manager.lock.assert_not_called()
    manager.stop_climate.assert_not_called()


@pytest.mark.parametrize('text,action,settings', [
    ('Tell Sirius to start the car 80 degrees with the seat warmers on two and rear defrost and defrost on.',
     'start_climate', {'temperature_f': 80, 'seat_heat': 2, 'rear_defrost': True, 'defrost': True}),
    ('Start the car.', 'start_climate', {'temperature_f': 72, 'duration': 10}),
    ('Stop the car.', 'stop_climate', {}),
    ('Lock.', 'lock', {}),
    ('Unlock.', 'unlock', {}),
    ('Start the car warm.', 'start_climate', {'temperature_f': 80, 'seat_heat': 3,
                                           'defrost': True, 'rear_defrost': True, 'duration': 10}),
    ('Turn the car on.', 'start_climate', {'temperature_f': 72}),
    ('Turn the car off.', 'stop_climate', {}),
    ('Start the car cool.', 'start_climate', {'temperature_f': 67, 'seat_ventilation': 2,
                                           'defrost': False, 'rear_defrost': False, 'duration': 10}),
    ('Cool my seat down.', 'start_climate', {'temperature_f': 67, 'driver_seat_ventilation': 2,
                                          'passenger_seat_ventilation': 0, 'duration': 10}),
    ('Lock the car.', 'lock', {}),
    ('Unlock the car.', 'unlock', {}),
])
def test_owner_phrase_corpus_previews_and_executes_once(bridge, text, action, settings):
    client, manager, factory = bridge
    preview = client.post('/parse_command', headers=HEADERS, json={'text': text})
    assert preview.status_code == 200, preview.json
    plan = preview.json['interpreted']
    assert plan['action'] == action
    assert all(plan['parameters'][key] == value for key, value in settings.items())
    factory.assert_not_called()
    response = client.post('/execute_command', headers=HEADERS, json={'text': text})
    assert response.status_code == 202, response.json
    assert response.json['interpreted'] == plan
    getattr(manager, action).assert_called_once()
    assert sum(getattr(manager, name).call_count for name in
               ('start_climate', 'stop_climate', 'lock', 'unlock')) == 1
    if text == 'Start the car warm.':
        options = manager.start_climate.call_args.args[1]
        assert (options.set_temp, options.front_left_seat, options.front_right_seat,
                options.defrost, options.heating) == (80, 8, 8, True, 1)
    if text == 'Start the car cool.':
        options = manager.start_climate.call_args.args[1]
        assert (options.set_temp, options.front_left_seat, options.front_right_seat,
                options.defrost, options.heating) == (67, 4, 4, False, 0)
    if text == 'Cool my seat down.':
        options = manager.start_climate.call_args.args[1]
        assert (options.set_temp, options.front_left_seat, options.front_right_seat,
                options.defrost, options.heating) == (67, 4, 2, False, 0)


@pytest.mark.parametrize('text,expected', [
    ('Tell Serious to start the car eighty degrees with seat warmers on too and rear de frost and de frost on.',
     {'temperature_f': 80, 'seat_heat': 2, 'rear_defrost': True, 'defrost': True}),
    ('start the car with seat warmers on to', {'seat_heat': 2}),
    ('start the car with driver seat warmer at too', {'driver_seat_heat': 2}),
    ('Start the car warm, at seventy-five degrees with seat warmers on one and defrost off.',
     {'temperature_f': 75, 'seat_heat': 1, 'defrost': False, 'rear_defrost': True}),
    ('start the car cool with seat vents at three', {'temperature_f': 67, 'seat_ventilation': 3}),
    ('start the car cool with seat heaters at one', {'temperature_f': 67, 'seat_heat': 1}),
    ('Tell Serious, to turn the car on cool.', {'temperature_f': 67, 'seat_ventilation': 2}),
])
def test_bounded_dictation_and_explicit_preset_overrides(bridge, text, expected):
    client, _, factory = bridge
    response = client.post('/parse_command', headers=HEADERS, json={'text': text})
    assert response.status_code == 200, response.json
    values = response.json['interpreted']['parameters']
    assert all(values[k] == v for k, v in expected.items())
    assert not ('seat_heat' in values and 'seat_ventilation' in values)
    factory.assert_not_called()


@pytest.mark.parametrize('text', [
    'do not turn the car on', 'turn the car off then on', 'turn the car not on',
    "don't tell Serious to unlock", 'start the car warm if it is cold',
    'unlock the core', 'start the car to degrees', 'start the car at too degrees',
    'start the car eighty five degrees', 'start the car with rear de frost on and rear defrost off',
    'start the car warm and cool', 'start the car warm and open a door',
    'cool my seat down tomorrow', 'cool my seat down and unlock',
    "don't cool my seat down",
])
def test_dictation_does_not_guess_actions_values_or_drop_negation(bridge, text):
    client, manager, factory = bridge
    response = client.post('/execute_command', headers=HEADERS, json={'text': text})
    assert response.status_code == 400, response.json
    assert response.json['message'] == response.json['error']
    factory.assert_not_called()
    assert not manager.mock_calls


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
    ("cool down my carnival with seat ventilation at 2", {"temperature_f": 67, "seat_ventilation": 2}),
    ("warm up my car with front defrost off", {"temperature_f": 80, "defrost": False}),
    ("start my car with turn on rear defrost", {"rear_defrost": True}),
    ("start my car at 62 F", {"temperature_f": 62}),
    ("start my car at 82 degrees for one minute", {"temperature_f": 82, "duration": 1}),
    ("prepare my car for winter", {"seat_heat": 3, "rear_defrost": True, "defrost": True}),
    ("start my car with winter preset and seat cooling at 3", {"seat_ventilation": 3}),
    ("start my car with seat heaters off", {"seat_heat": 0}),
    ("start my car with windshield defroster on", {"defrost": True}),
    ("turn on at 80 degrees with defrost and seat warmers at 2",
     {"temperature_f": 80, "defrost": True, "seat_heat": 2}),
    ("Siri, tell Sirius to turn on at 80 degrees with defrost and seat warmers at 2",
     {"temperature_f": 80, "defrost": True, "seat_heat": 2}),
    ("turn on Sirius at eighty degrees with rear defrost and seat warmers at two",
     {"temperature_f": 80, "rear_defrost": True, "defrost": False, "seat_heat": 2}),
    ("start with defrost off and rear defrost on", {"defrost": False, "rear_defrost": True}),
    ("set temperature to 72 degrees", {"temperature_f": 72}),
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
    ("unlock", "unlock"), ("lock", "lock"), ("turn off", "stop_climate"),
    ("unlock Sirius", "unlock"), ("lock the doors", "lock"),
    ("tell Sirius to unlock", "unlock"), ("Hey Siri, tell Sirius to unlock", "unlock"),
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
    "unlocking", "startled", "unlock something else", "turn on the lights",
    "don't unlock", "do not tell Sirius to unlock", "tell Sirius not to unlock",
    "Siri, tell Sirius to not unlock", "tell another car to unlock",
    "unlock and start", "tell Sirius to unlock tomorrow", "turn on if it is cold",
    "turn on with defrost and defrost off", "start with rear defrost and rear defrost off",
    "start with defrost maybe", "start with defrost off and defrost",
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
    assert response.json["unavailable"]["rear_seat_heat"] == "not equipped"
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


@pytest.mark.parametrize("text,driver,passenger", [
    ("start my car with driver seat warmer at three and passenger seat ventilation at two", 8, 4),
    ("start my car with driver's seat heater on low", 6, 2),
    ("start my car with passenger seat cooling at 3", 2, 5),
    ("prepare my car for winter with passenger seat off", 8, 2),
    ("prepare my car for winter with driver seat ventilation at 2", 4, 8),
    ("start my car with seat heaters at 3 and passenger seat warmer at 1", 8, 6),
    ("start my car with passenger seat ventilation at 1 and seat heaters at 2", 7, 3),
])
def test_individual_seat_commands_resolve_preview_and_execution(bridge, text, driver, passenger):
    client, manager, factory = bridge
    preview = client.post("/parse_command", headers=HEADERS, json={"text": text})
    assert preview.status_code == 200, preview.json
    factory.assert_not_called()
    params = preview.json["interpreted"]["parameters"]
    assert any(k.startswith("driver_seat_") for k in params)
    assert any(k.startswith("passenger_seat_") for k in params)
    response = client.post("/execute_command", headers=HEADERS, json={"text": text})
    assert response.status_code == 202, response.json
    manager.start_climate.assert_called_once()
    options = manager.start_climate.call_args.args[1]
    assert (options.front_left_seat, options.front_right_seat) == (driver, passenger)
    assert response.json["interpreted"] == preview.json["interpreted"]


def test_individual_seat_us_wire_payload():
    options = climate_options({"driver_seat_heat": 3, "passenger_seat_ventilation": 2})
    api = KiaUvoApiUSA.__new__(KiaUvoApiUSA)
    api.API_URL = "https://example.invalid/apigw/v1/"
    api.post_request_with_logging_and_active_session = Mock(
        return_value=SimpleNamespace(headers={"Xid": "test-id"}))
    api.start_climate(None, SimpleNamespace(), options)
    seats = api.post_request_with_logging_and_active_session.call_args.kwargs["json_body"]["remoteClimate"]["heatVentSeat"]
    assert seats["driverSeat"] == {"heatVentType": 1, "heatVentLevel": 4, "heatVentStep": 1}
    assert seats["passengerSeat"] == {"heatVentType": 2, "heatVentLevel": 3, "heatVentStep": 2}


@pytest.mark.parametrize("text", [
    "start my car with driver seat heat at 1 and driver seat ventilation at 2",
    "start my car with passenger seat heat off and passenger seat ventilation at 1",
    "start my car with driver seat heat at 1 and driver's seat heater at 2",
    "start my car with driver seat warmer at 4",
    "start my car with passenger seat ventilation at 3.5",
    "start my car with driver seat heat at 2 and rear seat heat at 1",
])
def test_invalid_individual_seat_commands_never_contact_kia(bridge, text):
    client, _, factory = bridge
    response = client.post("/execute_command", headers=HEADERS, json={"text": text})
    assert response.status_code == 400, response.json
    factory.assert_not_called()


@pytest.mark.parametrize("payload", [
    {"driver_seat_heat": True}, {"driver_seat_heat": -1},
    {"passenger_seat_ventilation": "2"}, {"passenger_seat_ventilation": 4},
    {"driver_seat_heat": 1, "driver_seat_ventilation": 0},
    {"passenger_seat_heat": 0, "passenger_seat_ventilation": 2},
])
def test_individual_structured_validation_rejects_before_kia(bridge, payload):
    client, _, factory = bridge
    assert client.post("/start_climate", headers=HEADERS, json=payload).status_code == 400
    factory.assert_not_called()
