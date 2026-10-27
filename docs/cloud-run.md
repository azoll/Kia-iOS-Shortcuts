# Cloud Run deployment

## Deployment contract

Run the existing Flask bridge in a non-root Python 3.12 container through Gunicorn. Listen on Cloud Run's `PORT`. Use one worker, one thread, request-based billing, zero minimum instances, a service-level maximum of one instance, 512 MiB RAM, and a 180-second request timeout. These settings reduce idle cost and overlapping Kia sessions; they do not impose a hard spending cap or prevent every overlap during a rollout.

Keep Kia username, password, remote-command PIN, and the bridge token in Google Secret Manager. The runtime service account gets access only to these four secrets. The Docker image and source upload must exclude local credentials. Pin secret versions when deploying.

The first deployment requires Google IAM authentication. Test health and parsing through an authenticated Cloud Run proxy before allowing direct access from iOS Shortcuts. Direct access still requires the bridge bearer token on every command route. Deployment and smoke checks must not send vehicle commands.

## Account prerequisites

Use a personal Google Cloud project with billing enabled. The monthly free allowances can cover a small personal service, but compute beyond those allowances, builds, image storage, secrets, and network traffic can incur charges. Configure a billing alert; alerts and maximum-instance settings are not hard spending limits.

The deployer needs permissions to enable APIs, create service accounts, grant the listed IAM roles, build containers, and deploy Cloud Run. See Google's [Flask quickstart](https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-service) for required roles and the [Secret Manager integration](https://docs.cloud.google.com/run/docs/configuring/services/secrets).

Never paste passwords, PINs, tokens, service-account keys, or an exported environment file into chat or GitHub.

## Prepare the personal project

For guided setup without navigating the API, service-account, or Secret Manager screens, run `bash scripts/setup-cloud-run.sh` from this branch in your own Cloud Shell. It shows the selected project for confirmation, prompts privately for missing Kia credentials, creates a random bridge token, and performs the setup below. If no project is selected it lists projects and asks for the personal project ID. Existing enabled secret versions are retained. No secret values are printed, and the resulting service still requires Google IAM authentication. Enter credentials only in your own Cloud Shell terminal, never in chat.

Open Google Cloud Shell in your own account. Create/select a personal project and enable its billing. In Cloud Shell, clone the reviewed deployment branch:

```bash
git clone --branch feat/carnival-siri-commands https://github.com/azoll/Kia-iOS-Shortcuts.git
cd Kia-iOS-Shortcuts
KIA_CLOUD_PROJECT="YOUR_PERSONAL_PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com --project="$KIA_CLOUD_PROJECT"
gcloud iam service-accounts create kia-siri-runtime --project="$KIA_CLOUD_PROJECT" --display-name="Kia Siri runtime"
gcloud iam service-accounts create kia-siri-build --project="$KIA_CLOUD_PROJECT" --display-name="Kia Siri builds"
gcloud projects add-iam-policy-binding "$KIA_CLOUD_PROJECT" --member="serviceAccount:kia-siri-build@${KIA_CLOUD_PROJECT}.iam.gserviceaccount.com" --role=roles/run.builder
```

Use Secret Manager's Create Secret form to create four secrets, each with an initial enabled version. Enter the values directly into Google, with these exact names:

| Secret | Value |
| - | - |
| `kia-username` | Kia account username |
| `kia-password` | Kia account password |
| `kia-pin` | Kia remote-command PIN, preserving leading zeros |
| `kia-bridge-token` | A newly generated random service token of at least 32 characters |

Generate the bridge token in your own terminal using `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. Save it in your password manager for the iPhone Shortcut. Do not reuse your Kia password as the token.

Give the runtime access to those secrets:

```bash
for secret in kia-username kia-password kia-pin kia-bridge-token; do
  gcloud secrets add-iam-policy-binding "$secret" --project="$KIA_CLOUD_PROJECT" --member="serviceAccount:kia-siri-runtime@${KIA_CLOUD_PROJECT}.iam.gserviceaccount.com" --role=roles/secretmanager.secretAccessor
done
bash scripts/deploy-cloud-run.sh "$KIA_CLOUD_PROJECT"
```

The script checks billing and secret-version metadata, builds from the source whitelist, and deploys a private service in `us-central1`. It never reads secret values or sends a Kia command. IAM changes may need time to propagate; do not repeatedly grant more roles to work around a propagation delay.

## Verify before enabling Siri access

Inspect the deployed revision: runtime service account, secret references, zero minimum and one maximum instance, concurrency one, and request-based billing. Check the source upload list with `gcloud meta list-files-for-upload`; only the container's runtime files should be uploaded. Do not upload `.env`.

Run a Google-authenticated proxy in Cloud Shell:

```bash
gcloud run services proxy kia-siri-bridge --project="$KIA_CLOUD_PROJECT" --region=us-central1 --port=8085
```

In a second Cloud Shell terminal, `curl --fail http://127.0.0.1:8085/` should return the health JSON. This does not initialize Kia. Stop the proxy when finished.

Before enabling direct access, review the service URL and authentication configuration. iOS Shortcuts needs the Cloud Run URL reachable without a Google identity token; the bridge's bearer token still protects command routes. Only after that review, grant public invocation:

```bash
gcloud run services add-iam-policy-binding kia-siri-bridge --project="$KIA_CLOUD_PROJECT" --region=us-central1 --member=allUsers --role=roles/run.invoker
```

Then run the HTTP smoke check with the bridge token entered privately in your own terminal:

```bash
read -r -s -p 'Bridge token: ' SECRET_KEY
echo
export SECRET_KEY
KIA_BRIDGE_URL="YOUR_DEPLOYED_HTTPS_URL"
python3 scripts/smoke-http.py "$KIA_BRIDGE_URL"
unset SECRET_KEY
```

That check verifies health, rejection without a token, and parsing of the 80-degree example. It does not execute a vehicle command. Next, use authenticated `/auth_status` and `/list_vehicles` to verify Kia access and vehicle selection. Set `VEHICLE_ID` on the service if needed. Test a single live command while parked, then install the Shortcut using this service URL and token.

Keep at most one active deployment serving traffic. The application lock is per process; maximum-instance settings do not provide a distributed lock during revision rollouts or all scaling edge cases. Avoid commands during deployments. If a command times out, its completion is unknown: check the vehicle before trying again.

To remove public invocation again:

```bash
gcloud run services remove-iam-policy-binding kia-siri-bridge --project="$KIA_CLOUD_PROJECT" --region=us-central1 --member=allUsers --role=roles/run.invoker
```

## Validation and status

If the username or password may have been entered incorrectly, run `python3 scripts/update-kia-credentials.py PROJECT_ID` in your own Cloud Shell. The email is visible so it can be checked; the password must be entered twice and stays hidden. No secret versions are changed if the two password entries differ. The helper creates new username/password secret versions through stdin and redeploys so Cloud Run uses the new versions. The PIN and bridge token are retained. It does not change the Kia account's actual password or execute any vehicle command.

For private HTTP verification from your own Cloud Shell, run `python3 scripts/check-cloud-run.py PROJECT_ID`. It reads the deployed bridge token's pinned secret version without printing it and uses separate Google and bridge authentication headers. It checks health, rejection without the bridge token, and parsing without Kia initialization. Add `--kia-login` to attempt Kia login once and list vehicle names/models/years if successful. These routes never actuate the vehicle. A failed login prints only a safe diagnostic category: missing configuration, required verification code, required account consent, or other authentication failure. It does not print upstream response details, tokens, passwords, or PINs.

The test workflow builds the Docker image and checks its HTTP health, authentication, and parser without Kia credentials. The Dockerfile uses an explicit runtime-file list and runs as a non-root user. These checks do not verify Google IAM, Cloud Build, Secret Manager integration, cold-start latency, or actual vehicle behavior. A successful Google deployment and live testing must be recorded separately.
