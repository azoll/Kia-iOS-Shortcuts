"""Correct stored Kia login details privately in the owner's Cloud Shell."""

import argparse
import getpass
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    args = parser.parse_args()
    # A terminal is required even when Python was launched with redirected stdin.
    with open("/dev/tty", "r") as keyboard, open("/dev/tty", "w") as terminal:
        terminal.write("Kia email (visible): ")
        terminal.flush()
        username = keyboard.readline().strip()
        password = getpass.getpass("Kia password (hidden): ", stream=terminal)
        confirmation = getpass.getpass("Repeat Kia password (hidden): ", stream=terminal)
    if not username or not password:
        raise SystemExit("Username and password must be nonempty. No secrets were changed.")
    if password != confirmation:
        raise SystemExit("The passwords did not match. No secrets were changed.")
    for name, value in (("kia-username", username), ("kia-password", password)):
        subprocess.run(["gcloud", "secrets", "versions", "add", name,
            "--project", args.project, "--data-file=-", "--quiet"],
            input=value.encode(), check=True, stdout=subprocess.DEVNULL)
    # Existing revisions pin secret versions, so new versions require deployment.
    deploy = Path(__file__).resolve().with_name("deploy-cloud-run.sh")
    subprocess.run(["bash", str(deploy), args.project], check=True)
    print("Credentials updated and service redeployed. PIN and bridge token unchanged.")
    print("Next: run scripts/check-cloud-run.py with --kia-login.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Cancelled. A partial secret update may need to be completed before redeploying.")
