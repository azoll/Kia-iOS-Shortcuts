"""Verify a private bridge from the account owner's Cloud Shell without actuation."""

import argparse
import json
import subprocess
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def gcloud(*args):
    return subprocess.check_output(["gcloud", *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--kia-login", action="store_true", help="Also attempt Kia login once")
    args = parser.parse_args()
    service = json.loads(gcloud("run", "services", "describe", "kia-siri-bridge",
        "--project", args.project, "--region", "us-central1", "--format=json"))
    url = service["status"]["url"].rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".run.app"):
        raise SystemExit("Unexpected service URL. No tokens were sent.")
    env = service["spec"]["template"]["spec"]["containers"][0]["env"]
    ref = next(e for e in env if e["name"] == "SECRET_KEY")["valueFrom"]["secretKeyRef"]
    token = gcloud("secrets", "versions", "access", str(ref["key"]),
        "--secret", ref["name"], "--project", args.project)
    identity = gcloud("auth", "print-identity-token")

    def check(path, expected=200, body=None, authenticated=True):
        headers = {"X-Serverless-Authorization": "Bearer " + identity}
        if authenticated:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = Request(url + path, headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(req, timeout=180) as response:
                status, result = response.status, json.load(response)
        except HTTPError as error:
            status = error.code
            try:
                result = json.load(error)
            except (ValueError, UnicodeError):
                result = {}
        print(f"{path}: HTTP {status}")
        if status != expected:
            # Never print upstream exception text, response headers, or tokens.
            code = result.get("error_code") if isinstance(result, dict) else None
            known = {"service_configuration_missing", "kia_otp_required",
                     "kia_consent_required", "kia_authentication_failed"}
            print("Diagnostic:", code if code in known else "unclassified")
            raise SystemExit(1)
        return result

    check("/")
    check("/capabilities", expected=401, authenticated=False)
    check("/parse_command", body={"text":
        "start my car at 80 degrees with seat warmers at 3 and rear defrost on"})
    if args.kia_login:
        check("/auth_status")
        vehicles = check("/list_vehicles")["vehicles"]
        print("Vehicles:", [{k: v.get(k) for k in ("name", "model", "year")} for v in vehicles])
    print("Checks passed. No vehicle commands were sent.")


if __name__ == "__main__":
    main()
