#!/usr/bin/env bash
# Run in your own Cloud Shell after completing docs/cloud-run.md.
set -euo pipefail
set +x

if (( $# < 1 || $# > 2 )); then
  echo "Usage: bash scripts/deploy-cloud-run.sh PROJECT_ID [REGION]" >&2
  exit 2
fi
project="$1"
region="${2:-us-central1}"
service="kia-siri-bridge"
runtime="kia-siri-runtime@${project}.iam.gserviceaccount.com"
builder="projects/${project}/serviceAccounts/kia-siri-build@${project}.iam.gserviceaccount.com"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

command -v gcloud >/dev/null || { echo "Use Google Cloud Shell or install gcloud first." >&2; exit 1; }
if [[ ! "$project" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]]; then
  echo "Supply the personal Google Cloud project ID, not its display name." >&2
  exit 2
fi
billing="$(gcloud billing projects describe "$project" --format='value(billingEnabled)')"
if [[ "${billing,,}" != true ]]; then
  echo "Billing is not enabled for this project. No deployment was attempted." >&2
  exit 1
fi

# Read secret metadata only. Pin the newest enabled version without reading values.
refs=()
for pair in KIA_USERNAME:kia-username KIA_PASSWORD:kia-password KIA_PIN:kia-pin SECRET_KEY:kia-bridge-token; do
  key="${pair%%:*}"
  secret="${pair#*:}"
  version="$(gcloud secrets versions list "$secret" --project="$project" \
    --filter='state=ENABLED' --sort-by='~createTime' --limit=1 --format='value(name)')"
  version="${version##*/}"
  if [[ ! "$version" =~ ^[0-9]+$ ]]; then
    echo "Create an enabled version of $secret before deploying." >&2
    exit 1
  fi
  refs+=("${key}=${secret}:${version}")
done
secret_refs="$(IFS=,; echo "${refs[*]}")"

gcloud run deploy "$service" --project="$project" --region="$region" \
  --source="$repo_root" --build-service-account="$builder" \
  --service-account="$runtime" --cpu=1 --memory=512Mi \
  --concurrency=1 --min=0 --max=1 --cpu-throttling --timeout=180 \
  --no-allow-unauthenticated --set-secrets="$secret_refs"

gcloud run services describe "$service" --project="$project" --region="$region" \
  --format='value(status.url)'
echo "Deployed with Google IAM authentication required. No vehicle command was sent."
