"""Complete Kia verification privately and store a minimal remembered session."""

import argparse
import getpass
import json
import logging
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hyundai_kia_connect_api import VehicleManager
from hyundai_kia_connect_api.ApiImpl import OTPRequest
from hyundai_kia_connect_api.const import OTP_NOTIFY_TYPE
from hyundai_kia_connect_api.exceptions import AuthenticationError

from kia_session import SessionConfigurationError, save_remembered_session


def gcloud(*args, input_data=None, strip=True):
    response = subprocess.run(["gcloud", *args], input=input_data,
                              capture_output=True, check=True)
    result = response.stdout.decode()
    return result.strip() if strip else result


def deployed_credentials(project):
    service = json.loads(gcloud("run", "services", "describe", "kia-siri-bridge",
        "--project", project, "--region", "us-central1", "--format=json"))
    env = service["spec"]["template"]["spec"]["containers"][0]["env"]
    values = {}
    for field in ("KIA_USERNAME", "KIA_PASSWORD", "KIA_PIN"):
        ref = next(e for e in env if e["name"] == field)["valueFrom"]["secretKeyRef"]
        values[field] = gcloud("secrets", "versions", "access", str(ref["key"]),
            "--secret", ref["name"], "--project", project, strip=False)
    return values


def authenticate(manager, choose=input, read_code=getpass.getpass):
    result = manager.login()
    if result is True:
        return
    if not isinstance(result, OTPRequest):
        raise AuthenticationError()
    methods = {}
    if result.has_email:
        methods["email"] = OTP_NOTIFY_TYPE.EMAIL
    if result.has_sms:
        methods["sms"] = OTP_NOTIFY_TYPE.SMS
    if not methods:
        raise AuthenticationError()
    if len(methods) == 1:
        method = next(iter(methods))
    else:
        method = choose("Send Kia verification code by email or sms? ").strip().lower()
    if method not in methods:
        raise SystemExit("Choose an available email or sms method. No code was requested.")
    print(f"Requesting Kia verification code by {method}.")
    manager.send_otp(methods[method])
    code = read_code("Kia verification code (hidden): ").strip()
    if not code or len(code) > 32:
        raise SystemExit("Invalid verification-code input. No session was saved.")
    manager.verify_otp_and_complete_login(code)


def persist_session(project, serialized):
    names = gcloud("secrets", "list", "--project", project, "--format=value(name)").splitlines()
    exists = any(name.rsplit("/", 1)[-1] == "kia-session" for name in names)
    if exists:
        gcloud("secrets", "versions", "add", "kia-session", "--project", project,
               "--data-file=-", "--quiet", input_data=serialized.encode())
    else:
        gcloud("secrets", "create", "kia-session", "--project", project,
               "--replication-policy=automatic", "--data-file=-", "--quiet",
               input_data=serialized.encode())
    gcloud("secrets", "add-iam-policy-binding", "kia-session", "--project", project,
        "--member=serviceAccount:kia-siri-runtime@" + project + ".iam.gserviceaccount.com",
        "--role=roles/secretmanager.secretAccessor", "--quiet")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    args = parser.parse_args()
    # The upstream library may log raw responses. Suppress logs in this helper.
    logging.disable(logging.CRITICAL)
    credentials = deployed_credentials(args.project)
    manager = VehicleManager(region=3, brand=1, username=credentials["KIA_USERNAME"],
        password=credentials["KIA_PASSWORD"], pin=credentials["KIA_PIN"])
    authenticate(manager)
    serialized = save_remembered_session(manager.token)
    persist_session(args.project, serialized)
    print("Remembered session saved in Secret Manager. No tokens or codes were printed.")
    deploy = Path(__file__).resolve().with_name("deploy-cloud-run.sh")
    subprocess.run(["bash", str(deploy), args.project], check=True)
    print("Private service redeployed with the remembered session. No vehicle commands sent.")


if __name__ == "__main__":
    try:
        main()
    except AuthenticationError:
        sys.exit("Kia sign-in or verification failed. No remembered session was saved.")
    except SessionConfigurationError:
        sys.exit("Kia did not provide a valid remembered session. No session was saved.")
    except subprocess.CalledProcessError:
        sys.exit("A Google Cloud operation failed. If session storage completed, retry deployment without requesting another code.")
    except KeyboardInterrupt:
        sys.exit("Enrollment cancelled. No vehicle commands were sent.")
    except Exception:
        sys.exit("Enrollment could not finish. Private error details were suppressed.")
