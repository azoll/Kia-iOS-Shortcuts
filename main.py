"""Authenticated Siri command bridge for a U.S. Kia Connect account."""

import hmac
import os
from functools import wraps
from threading import RLock

from flask import Flask, jsonify, request
from hyundai_kia_connect_api import ClimateRequestOptions, VehicleManager
from hyundai_kia_connect_api.exceptions import AuthenticationError
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from natural_language import CommandParseError, parse_command


PRESETS = {
    "default": {"temperature_f": 72, "duration": 10, "defrost": False},
    "warm": {"temperature_f": 74, "duration": 10, "defrost": True},
    "cool": {"temperature_f": 68, "duration": 10, "defrost": False},
    "winter": {"temperature_f": 74, "duration": 10, "defrost": True,
               "rear_defrost": True, "seat_heat": 3},
}
REQUIRED_SETTINGS = ("KIA_USERNAME", "KIA_PASSWORD", "KIA_PIN", "SECRET_KEY")
SEAT_FIELDS = tuple(prefix + mode for prefix in ("", "driver_", "passenger_")
                    for mode in ("seat_heat", "seat_ventilation"))


class InputError(Exception):
    """The command payload is invalid."""


class VehicleSelectionError(Exception):
    """The account cannot resolve the intended vehicle."""


class ServiceConfigurationError(Exception):
    """Required service settings are absent."""


def climate_settings(payload):
    """Resolve defaults and validate the complete climate request."""
    if not isinstance(payload, dict):
        raise InputError("The request body must be a JSON object.")
    unknown = payload.keys() - ({"preset", "temperature_f", "duration", "defrost",
                                 "rear_defrost"} | set(SEAT_FIELDS))
    if unknown:
        raise InputError("The climate request contains unsupported fields.")
    preset = payload.get("preset", "default")
    if not isinstance(preset, str) or preset not in PRESETS:
        raise InputError("Preset must be default, warm, cool, or winter.")
    values = {"rear_defrost": False} | PRESETS[preset] | {
        k: v for k, v in payload.items() if k != "preset"
    }
    # A requested seat mode replaces the mode inherited from a preset.
    if "seat_heat" in payload and "seat_ventilation" in payload:
        raise InputError("Choose front-seat heating or ventilation, not a combination.")
    if "seat_ventilation" in payload:
        values.pop("seat_heat", None)
    if "seat_heat" in payload:
        values.pop("seat_ventilation", None)
    temperature = values["temperature_f"]
    if type(temperature) is not int or not 62 <= temperature <= 82:
        raise InputError("temperature_f must be a whole number from 62 to 82.")
    duration = values["duration"]
    if type(duration) is not int or not 1 <= duration <= 10:
        raise InputError("duration must be a whole number from 1 to 10 minutes.")
    if type(values["defrost"]) is not bool:
        raise InputError("defrost must be true or false.")
    if type(values["rear_defrost"]) is not bool:
        raise InputError("rear_defrost must be true or false.")
    for field in SEAT_FIELDS:
        if field in values and (type(values[field]) is not int or not 0 <= values[field] <= 3):
            raise InputError(f"{field} must be a whole number from 0 to 3.")
    if any(field in payload for field in SEAT_FIELDS if field.startswith(("driver_", "passenger_"))):
        # The U.S. adapter sends every seat when any seat is requested. Resolve
        # the other front seat to off unless a shared setting/preset supplies it.
        shared_mode = "seat_ventilation" if "seat_ventilation" in values else "seat_heat"
        shared_level = values.get(shared_mode, 0)
        for seat in ("driver", "passenger"):
            heat, vent = f"{seat}_seat_heat", f"{seat}_seat_ventilation"
            if heat in payload and vent in payload:
                raise InputError(f"Choose heating or ventilation for the {seat} seat.")
            if heat not in payload and vent not in payload:
                values[f"{seat}_{shared_mode}"] = shared_level
        values.pop("seat_heat", None)
        values.pop("seat_ventilation", None)
    return values


def climate_options(payload):
    """Map validated front-seat levels and defrost to U.S. Kia fields."""
    values = climate_settings(payload)
    seats = {}
    for seat, option in (("driver", "front_left_seat"), ("passenger", "front_right_seat")):
        for mode, offset in (("seat_heat", 5), ("seat_ventilation", 2)):
            field = f"{seat}_{mode}" if f"{seat}_{mode}" in values else mode
            if field in values:
                level = values[field]
                seats[option] = offset + level if level else 2
    return ClimateRequestOptions(
        set_temp=values["temperature_f"],
        duration=values["duration"],
        defrost=values["defrost"],
        climate=True,
        heating=1 if values["rear_defrost"] else 0,
        steering_wheel=0,
        **seats,
    )


def create_app(environ=None, manager_factory=VehicleManager):
    """Build the app without signing in or sending a vehicle command."""
    settings = dict(os.environ if environ is None else environ)
    app = Flask(__name__)
    manager = None
    command_lock = RLock()

    def authenticated(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            secret = settings.get("SECRET_KEY", "")
            if len(secret) < 32:
                return jsonify(error="Service authentication is not configured."), 503
            supplied = request.headers.get("Authorization", "")
            if supplied.startswith("Bearer "):
                supplied = supplied[7:]
            # The raw token remains compatible with upstream iOS shortcuts.
            if not hmac.compare_digest(supplied.encode(), secret.encode()):
                return jsonify(error="Unauthorized"), 401
            try:
                # The library mutates shared tokens and vehicle state.
                with command_lock:
                    return fn(*args, **kwargs)
            except (BadRequest, UnsupportedMediaType):
                return jsonify(error="Send a valid JSON object with application/json."), 400
            except (InputError, CommandParseError) as exc:
                return jsonify(error=str(exc)), 400
            except VehicleSelectionError as exc:
                return jsonify(error=str(exc)), 409
            except ServiceConfigurationError:
                return jsonify(error="Configure the required service settings first."), 503
            except AuthenticationError:
                return jsonify(
                    error="Kia authentication requires attention.",
                    message="Verify the service credentials and Kia authentication requirements.",
                ), 503
            except Exception:
                # Upstream exception strings can contain account or session data.
                return jsonify(error="Kia could not process the request. Completion is unknown."), 502
        return wrapped

    def get_manager():
        nonlocal manager
        if any(not settings.get(key) for key in REQUIRED_SETTINGS):
            raise ServiceConfigurationError()
        if manager is None:
            manager = manager_factory(
                region=3,
                brand=1,
                username=settings["KIA_USERNAME"],
                password=settings["KIA_PASSWORD"],
                pin=settings["KIA_PIN"],
            )
        manager.check_and_refresh_token()
        return manager

    def selected_vehicle(client):
        vehicle_id = settings.get("VEHICLE_ID")
        if vehicle_id:
            if vehicle_id not in client.vehicles:
                raise VehicleSelectionError("VEHICLE_ID does not match a vehicle on the account.")
            return vehicle_id
        if len(client.vehicles) != 1:
            raise VehicleSelectionError("Set VEHICLE_ID to select the intended vehicle.")
        return next(iter(client.vehicles))

    def submitted(command, command_id):
        if not isinstance(command_id, str) or not command_id:
            return jsonify(error="Kia did not provide a command identifier. Completion is unknown."), 502
        return jsonify(
            status="submitted",
            command=command,
            command_id=command_id,
            message="Request submitted to Kia. Vehicle completion is not yet confirmed.",
        ), 202

    @app.get("/")
    def root():
        return jsonify(status="ok", service="Carnival Siri bridge")

    @app.get("/auth_status")
    @authenticated
    def auth_status():
        get_manager()
        return jsonify(status="authenticated")

    @app.get("/list_vehicles")
    @authenticated
    def list_vehicles():
        client = get_manager()
        return jsonify(vehicles=[
            {"id": v.id, "name": v.name, "model": v.model, "year": v.year}
            for v in client.vehicles.values()
        ])

    @app.get("/capabilities")
    @authenticated
    def capabilities():
        return jsonify(
            vehicle="2026 Kia Carnival Hybrid SX (U.S.)",
            implemented=["start_climate", "stop_climate", "lock", "unlock",
                         "front_seat_heat", "front_seat_ventilation", "rear_mirror_defrost",
                         "individual_front_seat_settings"],
            live_vehicle_verified=False,
            unavailable={"heated_steering_wheel": "not equipped",
                         "rear_seat_heat": "not equipped",
                         "power_sliding_doors": "U.S. command unverified",
                         "power_liftgate": "U.S. command unverified",
                         "horn_lights": "U.S. command not implemented"},
        )

    def interpreted_command():
        payload = request.get_json()
        if not isinstance(payload, dict) or set(payload) != {"text"}:
            raise InputError("Send a JSON object containing only text.")
        plan = parse_command(payload["text"])
        if plan["action"] == "start_climate":
            plan["parameters"] = climate_settings(plan["parameters"])
        return plan

    @app.post("/parse_command")
    @authenticated
    def preview_command():
        return jsonify(status="preview", interpreted=interpreted_command())

    @app.post("/execute_command")
    @authenticated
    def execute_command():
        plan = interpreted_command()
        client = get_manager()
        vehicle_id = selected_vehicle(client)
        if plan["action"] == "start_climate":
            result = client.start_climate(vehicle_id, climate_options(plan["parameters"]))
        else:
            methods = {"stop_climate": client.stop_climate,
                       "lock": client.lock, "unlock": client.unlock}
            result = methods[plan["action"]](vehicle_id)
        response, status = submitted(plan["action"], result)
        if status == 202:
            return jsonify(response.get_json() | {"interpreted": plan}), status
        return response, status

    @app.post("/start_climate")
    @authenticated
    def start_climate():
        options = climate_options(request.get_json() if request.get_data() else {})
        client = get_manager()
        return submitted("start_climate", client.start_climate(selected_vehicle(client), options))

    def simple_command(command, method):
        # These commands accept no parameters. Reject accidental or misspelled bodies.
        if request.get_data() and request.get_json() != {}:
            raise InputError("This command accepts an empty JSON object only.")
        client = get_manager()
        return submitted(command, getattr(client, method)(selected_vehicle(client)))

    @app.post("/stop_climate")
    @authenticated
    def stop_climate():
        return simple_command("stop_climate", "stop_climate")

    @app.post("/lock_car")
    @authenticated
    def lock_car():
        return simple_command("lock", "lock")

    @app.post("/unlock_car")
    @authenticated
    def unlock_car():
        return simple_command("unlock", "unlock")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080)
