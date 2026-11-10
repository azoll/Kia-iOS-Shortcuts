"""Minimal remembered Kia session storage, excluding password, PIN and session ID."""

from datetime import datetime, UTC
import json
from uuid import UUID

from hyundai_kia_connect_api.Token import Token


class SessionConfigurationError(ValueError):
    """Saved session data is invalid or belongs to another configured account."""


def validate(data, username):
    fields = {"version", "username", "device_id", "refresh_token"}
    if not isinstance(data, dict) or set(data) != fields:
        raise SessionConfigurationError()
    if type(data["version"]) is not int or data["version"] != 1:
        raise SessionConfigurationError()
    for field, limit in (("username", 512), ("device_id", 128), ("refresh_token", 8192)):
        if not isinstance(data[field], str) or not 1 <= len(data[field]) <= limit:
            raise SessionConfigurationError()
    if data["username"] != username:
        raise SessionConfigurationError()
    try:
        UUID(data["device_id"])
    except (ValueError, AttributeError) as error:
        raise SessionConfigurationError() from error
    return data


def save_remembered_session(token):
    data = {"version": 1, "username": token.username,
            "device_id": token.device_id, "refresh_token": token.refresh_token}
    validate(data, token.username)
    return json.dumps(data)


def load_remembered_session(raw, username, password, pin):
    if not isinstance(raw, str) or len(raw) > 16384:
        raise SessionConfigurationError()
    try:
        data = validate(json.loads(raw), username)
    except (ValueError, TypeError) as error:
        raise SessionConfigurationError() from error
    # Always refresh the remembered session on first access after a cold start.
    return Token(username=username, password=password, pin=pin,
                 device_id=data["device_id"], refresh_token=data["refresh_token"],
                 valid_until=datetime.min.replace(tzinfo=UTC))
