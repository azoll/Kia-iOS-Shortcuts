"""Authenticated Siri command bridge for a U.S. Kia Connect account."""

import hmac
import os
from functools import wraps
from threading import RLock

from flask import Flask, jsonify, request
from hyundai_kia_connect_api import ClimateRequestOptions, VehicleManager
from hyundai_kia_connect_api.exceptions import AuthenticationError
from werkzeug.exceptions import BadRequest, UnsupportedMediaType


PRESETS = {
    "default": {"temperature_f": 72, "duration": 10, "defrost": False},
    "warm": {"temperature_f": 74, "duration": 10, "defrost": True},
    "cool": {"temperature_f": 68, "duration": 10, "defrost": False},
}
REQUIRED_SETTINGS = ("KIA_USERNAME", "KIA_PASSWORD", "KIA_PIN", "SECRET_KEY")


class InputError(Exception):
    """The command payload is invalid."""


class VehicleSelectionError(Exception):
    """The account cannot resolve the intended vehicle."""


class ServiceConfigurationError(Exception):
    """Required service settings are absent."""


def climate_options(payload):
    """Validate explicit Fahrenheit fields before contacting Kia."""
    if not isinstance(payload, dict):
        raise InputError("The request body must be a JSON object.")
    unknown = payload.keys() - {"preset", "temperature_f", "duration", "defrost"}
    if unknown:
        raise InputError("The climate request contains unsupported fields.")
    preset = payload.get("preset", "default")
    if not isinstance(preset, str) or preset not in PRESETS:
        raise InputError("Preset must be default, warm, or cool.")
    values = PRESETS[preset] | {k: v for k, v in payload.items() if k != "preset"}
    temperature = values["temperature_f"]
    if type(temperature) is not int or not 62 <= temperature <= 82:
        raise InputError("temperature_f must be a whole number from 62 to 82.")
    duration = values["duration"]
    if type(duration) is not int or not 1 <= duration <= 10:
        raise InputError("duration must be a whole number from 1 to 10 minutes.")
    if type(values["defrost"]) is not bool:
        raise InputError("defrost must be true or false.")
    return ClimateRequestOptions(
        set_temp=temperature,
        duration=duration,
        defrost=values["defrost"],
        climate=True,
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
            except InputError as exc:
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
