"""Check HTTP/auth/parsing without Kia credentials or vehicle commands."""

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

base = sys.argv[1].rstrip("/")
token = os.environ["SECRET_KEY"]


def request(path, payload=None, authenticated=True):
    headers = {"Authorization": f"Bearer {token}"} if authenticated else {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                  headers=headers)
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


for attempt in range(30):
    try:
        status, data = request("/", authenticated=False)
        assert status == 200 and data["status"] == "ok"
        break
    except (URLError, ConnectionError, TimeoutError):
        if attempt == 29:
            raise
        time.sleep(0.5)

assert request("/capabilities", authenticated=False)[0] == 401
status, data = request("/parse_command", {
    "text": "start my car at 80 degrees with driver seat warmer at 3 and rear defrost on"})
assert status == 200, status
assert data["interpreted"]["parameters"]["temperature_f"] == 80
assert data["interpreted"]["parameters"]["driver_seat_heat"] == 3
assert data["interpreted"]["parameters"]["passenger_seat_heat"] == 0
assert data["interpreted"]["parameters"]["rear_defrost"] is True
print("HTTP health, authentication, and command preview passed. No vehicle command sent.")
