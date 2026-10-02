#!/usr/bin/env bash
# Manual deploy, the same steps as .github/workflows/deploy.yml. Use it when GitHub Actions isn't available.
# Needs deploy/bootstrap.sh to have run once. Builds the image with Cloud Build (no local Docker needed).
#
#   ./deploy/deploy.sh
#   FIREBASE_API_KEY=... FIREBASE_APP_ID=... ./deploy/deploy.sh      # with Firebase sign-in
set -euo pipefail

PROJECT="${PROJECT:-sf-hacks-tutor}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-throughline}"
cd "$(dirname "$0")/.."

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%s)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/throughline/throughline:${TAG}"

echo "== Building ${IMAGE} with Cloud Build"
gcloud builds submit --project "${PROJECT}" --tag "${IMAGE}" .

ENV="STORE=firestore,GOOGLE_CLOUD_PROJECT=${PROJECT},LOG_FORMAT=json,BULLETIN_LIVE=1"
ENV="${ENV},BUILD_QUEUE=cloudtasks,PUBLIC_URL=${URL},TASKS_LOCATION=${REGION},TASKS_QUEUE=course-builds"
ENV="${ENV},TASKS_INVOKER_SA=throughline-tasks@${PROJECT}.iam.gserviceaccount.com"
if [[ -n "${FIREBASE_API_KEY:-}" ]]; then
  ENV="${ENV},AUTH_MODE=firebase,FIREBASE_API_KEY=${FIREBASE_API_KEY},FIREBASE_APP_ID=${FIREBASE_APP_ID:?set FIREBASE_APP_ID too}"
  ENV="${ENV},FIREBASE_AUTH_DOMAIN=${PROJECT}.firebaseapp.com"
else
  ENV="${ENV},AUTH_MODE=demo"
fi
[[ -n "${ALLOWED_EMAIL_DOMAINS:-}" ]] && ENV="${ENV},ALLOWED_EMAIL_DOMAINS=${ALLOWED_EMAIL_DOMAINS}"
SECRETS=()
if gcloud secrets describe gemini-api-key --project "${PROJECT}" >/dev/null 2>&1; then
  SECRETS=(--set-secrets "GEMINI_API_KEY=gemini-api-key:latest")
else
  ENV="${ENV},GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_LOCATION=global"
fi

echo "== Deploying ${SERVICE}"
gcloud run deploy "${SERVICE}" --image "${IMAGE}" --region "${REGION}" --project "${PROJECT}" \
  --service-account "throughline-run@${PROJECT}.iam.gserviceaccount.com" \
  --allow-unauthenticated --execution-environment gen2 \
  --cpu 1 --memory 1Gi --no-cpu-throttling --cpu-boost \
  --min-instances 1 --max-instances 1 --concurrency 60 --timeout 900 \
  --startup-probe "httpGet.path=/api/health,httpGet.port=8080,periodSeconds=3,timeoutSeconds=2,failureThreshold=20" \
  --liveness-probe "httpGet.path=/api/health,httpGet.port=8080,periodSeconds=30,timeoutSeconds=5,failureThreshold=3" \
  --set-env-vars "${ENV}" "${SECRETS[@]}" --labels "app=throughline,commit=${TAG}" --quiet

echo "== Smoke test"
for path in /api/health /api/ready /; do
  printf '%-12s %s\n' "${path}" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "${URL}${path}")"
done
echo "Health: $(curl -s "${URL}/api/health")"
echo "Live at ${URL}"
