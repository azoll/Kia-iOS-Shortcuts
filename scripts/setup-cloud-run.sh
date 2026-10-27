#!/usr/bin/env bash
# Interactive setup in Andrew's personal Google Cloud Shell, never in chat.
set -euo pipefail
set +x

command -v gcloud >/dev/null || { echo "Open Google Cloud Shell before running this script." >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3 is required." >&2; exit 1; }
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
project="${1:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "$project" || "$project" == '(unset)' ]]; then
  gcloud projects list --format='table(projectId,name)'
  read -r -p 'Personal project ID from the list: ' project </dev/tty
fi
if [[ ! "$project" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]]; then
  echo "A valid personal project ID is required. No resources were changed." >&2
  exit 2
fi
billing="$(gcloud billing projects describe "$project" --format='value(billingEnabled)')"
if [[ "${billing,,}" != true ]]; then
  echo "Billing is not enabled on $project. No resources were changed." >&2
  exit 1
fi

echo "Project: $project"
echo "Setup enables the Cloud Run/build/secrets APIs, creates two service accounts,"
echo "stores the Kia credentials in Google Secret Manager, and deploys a private service."
echo "Google's free allowances apply; usage beyond them can incur charges."
read -r -p 'Use this personal project? Type deploy: ' confirmation </dev/tty
if [[ "$confirmation" != deploy ]]; then
  echo "Stopped without changing resources."
  exit 0
fi

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iam.googleapis.com --project="$project" --quiet
for account in kia-siri-runtime kia-siri-build; do
  email="${account}@${project}.iam.gserviceaccount.com"
  existing="$(gcloud iam service-accounts list --project="$project" \
    --filter="email=$email" --format='value(email)')"
  if [[ -z "$existing" ]]; then
    gcloud iam service-accounts create "$account" --project="$project" --display-name="$account" --quiet
  fi
done
gcloud projects add-iam-policy-binding "$project" \
  --member="serviceAccount:kia-siri-build@${project}.iam.gserviceaccount.com" \
  --role=roles/run.builder --quiet >/dev/null

for pair in kia-username:Username kia-password:Password kia-pin:PIN kia-bridge-token:Token; do
  secret="${pair%%:*}"
  label="${pair#*:}"
  existing_names="$(gcloud secrets list --project="$project" --format='value(name)')"
  exists=false
  while IFS= read -r name; do
    if [[ "${name##*/}" == "$secret" ]]; then exists=true; fi
  done <<< "$existing_names"
  version=""
  if [[ "$exists" == true ]]; then
    version="$(gcloud secrets versions list "$secret" --project="$project" \
      --filter='state=ENABLED' --sort-by='~createTime' --limit=1 --format='value(name)')"
  fi
  if [[ -z "$version" ]]; then
    if [[ "$secret" == kia-bridge-token ]]; then
      value="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    else
      value=""
      until [[ -n "$value" ]]; do
        read -r -s -p "Kia $label (hidden; sent only to Google Secret Manager): " value </dev/tty
        printf '\n' >/dev/tty
      done
    fi
    if [[ "$exists" == true ]]; then
      printf '%s' "$value" | gcloud secrets versions add "$secret" \
        --project="$project" --data-file=- --quiet >/dev/null
    else
      printf '%s' "$value" | gcloud secrets create "$secret" \
        --project="$project" --replication-policy=automatic --data-file=- --quiet >/dev/null
    fi
    unset value
  else
    echo "Keeping the existing enabled version of $secret."
  fi
  gcloud secrets add-iam-policy-binding "$secret" --project="$project" \
    --member="serviceAccount:kia-siri-runtime@${project}.iam.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor --quiet >/dev/null
done

bash "$repo_root/scripts/deploy-cloud-run.sh" "$project"
echo "Private deployment complete. Kia credentials and the bridge token were not printed."
echo "The bridge token is stored in Secret Manager as kia-bridge-token."
echo "Next: verify the private service, then review enabling direct Siri access."
