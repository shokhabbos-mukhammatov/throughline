#!/usr/bin/env bash
# One-time Google Cloud setup for Throughline. Safe to re-run: every step skips what already exists.
#
#   gcloud auth login
#   ./deploy/bootstrap.sh                                # uses the defaults below
#   GEMINI_API_KEY=... ./deploy/bootstrap.sh             # also stores a Gemini API key in Secret Manager
#
# Creates: APIs, Firestore, an Artifact Registry repository, a Cloud Tasks queue, three service accounts
# (runtime, Cloud Tasks invoker, GitHub deployer), and Workload Identity Federation so GitHub Actions can
# deploy without any stored key. Prints the GitHub repository variables to set at the end.
set -euo pipefail

PROJECT="${PROJECT:-sf-hacks-tutor}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-throughline}"
GITHUB_REPO="${GITHUB_REPO:?set GITHUB_REPO=owner/repo, the repository allowed to deploy}"
QUEUE="${QUEUE:-course-builds}"
REPO="${REPO:-throughline}"  # Artifact Registry repository

RUNTIME_SA="throughline-run@${PROJECT}.iam.gserviceaccount.com"
TASKS_SA="throughline-tasks@${PROJECT}.iam.gserviceaccount.com"
DEPLOY_SA="throughline-deployer@${PROJECT}.iam.gserviceaccount.com"

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
exists() { "$@" >/dev/null 2>&1; }
g() { gcloud --project "${PROJECT}" --quiet "$@"; }

step "Project ${PROJECT}"
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
echo "project number ${PROJECT_NUMBER}"
SERVICE_URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"

step "Enabling APIs (takes a minute the first time)"
g services enable \
  run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  firestore.googleapis.com aiplatform.googleapis.com cloudtasks.googleapis.com \
  secretmanager.googleapis.com iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  logging.googleapis.com monitoring.googleapis.com \
  firebase.googleapis.com identitytoolkit.googleapis.com

step "Firestore (native mode, ${REGION})"
if exists g firestore databases describe --database="(default)"; then echo "exists"
else g firestore databases create --database="(default)" --location="${REGION}" --type=firestore-native; fi

step "Artifact Registry repository ${REPO}"
if exists g artifacts repositories describe "${REPO}" --location="${REGION}"; then echo "exists"
else g artifacts repositories create "${REPO}" --repository-format=docker --location="${REGION}" --description="Throughline images"; fi

step "Cloud Tasks queue ${QUEUE}"
if exists g tasks queues describe "${QUEUE}" --location="${REGION}"; then echo "exists"
else g tasks queues create "${QUEUE}" --location="${REGION}" --max-attempts=3 --max-concurrent-dispatches=4 --min-backoff=30s --max-backoff=300s; fi

step "Service accounts"
make_sa() {  # name, display name
  if exists g iam service-accounts describe "$1@${PROJECT}.iam.gserviceaccount.com"; then echo "$1 exists"
  else g iam service-accounts create "$1" --display-name="$2"; fi
}
make_sa throughline-run "Throughline Cloud Run runtime"
make_sa throughline-tasks "Throughline Cloud Tasks invoker"
make_sa throughline-deployer "Throughline GitHub deployer"
sleep 5  # new service accounts take a moment to become visible to IAM

bind_project() {  # member, role
  g projects add-iam-policy-binding "${PROJECT}" --member="$1" --role="$2" --condition=None >/dev/null
  echo "  $2 -> $1"
}
step "Runtime permissions (least privilege)"
for role in roles/datastore.user roles/aiplatform.user roles/cloudtasks.enqueuer roles/logging.logWriter \
            roles/monitoring.metricWriter roles/cloudtrace.agent; do
  bind_project "serviceAccount:${RUNTIME_SA}" "${role}"
done
# The runtime creates tasks that Cloud Tasks signs as the invoker account, which needs actAs on it.
g iam service-accounts add-iam-policy-binding "${TASKS_SA}" --member="serviceAccount:${RUNTIME_SA}" \
  --role=roles/iam.serviceAccountUser >/dev/null && echo "  runtime may act as the tasks invoker"

step "Deployer permissions"
for role in roles/run.admin roles/artifactregistry.writer roles/secretmanager.viewer; do
  bind_project "serviceAccount:${DEPLOY_SA}" "${role}"
done
g iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" --member="serviceAccount:${DEPLOY_SA}" \
  --role=roles/iam.serviceAccountUser >/dev/null && echo "  deployer may deploy as the runtime account"

step "Cloud Build (used by the manual deploy/deploy.sh)"
BUILD_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for role in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
  bind_project "serviceAccount:${BUILD_SA}" "${role}"
done

step "Workload Identity Federation for GitHub Actions (${GITHUB_REPO})"
if exists g iam workload-identity-pools describe github --location=global; then echo "pool exists"
else g iam workload-identity-pools create github --location=global --display-name="GitHub Actions"; fi
if exists g iam workload-identity-pools providers describe github --location=global --workload-identity-pool=github; then echo "provider exists"
else
  g iam workload-identity-pools providers create-oidc github --location=global --workload-identity-pool=github \
    --display-name="GitHub" --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='${GITHUB_REPO}'"
fi
POOL="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github"
g iam service-accounts add-iam-policy-binding "${DEPLOY_SA}" --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/${POOL}/attribute.repository/${GITHUB_REPO}" >/dev/null
echo "  only ${GITHUB_REPO} may deploy"

if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  step "Secret Manager: gemini-api-key"
  if exists g secrets describe gemini-api-key; then
    printf '%s' "${GEMINI_API_KEY}" | g secrets versions add gemini-api-key --data-file=- >/dev/null && echo "new version added"
  else
    printf '%s' "${GEMINI_API_KEY}" | g secrets create gemini-api-key --replication-policy=automatic --data-file=- >/dev/null && echo "created"
  fi
  g secrets add-iam-policy-binding gemini-api-key --member="serviceAccount:${RUNTIME_SA}" \
    --role=roles/secretmanager.secretAccessor >/dev/null && echo "  runtime may read it"
fi

cat <<EOF

Done. Set these in GitHub: repository Settings -> Secrets and variables -> Actions -> Variables tab
(they are identifiers, not secrets):

  GCP_PROJECT_ID          ${PROJECT}
  GCP_PROJECT_NUMBER      ${PROJECT_NUMBER}
  GCP_REGION              ${REGION}
  GCP_WIF_PROVIDER        ${POOL}/providers/github
  GCP_DEPLOY_SA           ${DEPLOY_SA}

The service will live at ${SERVICE_URL}
Next: Firebase sign-in (docs/GUIDE.md, section 4, step 3), then push to main or run the "Deploy" workflow.
EOF
