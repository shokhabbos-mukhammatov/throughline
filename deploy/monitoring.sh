#!/usr/bin/env bash
# Uptime check + email alert for the deployed service. Run once after the first deploy.
#
#   ALERT_EMAIL=you@sfsu.edu ./deploy/monitoring.sh
#
# Checks GET /api/health every minute from several regions; emails ALERT_EMAIL when it fails for 5 minutes.
set -euo pipefail

PROJECT="${PROJECT:-sf-hacks-tutor}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-throughline}"
: "${ALERT_EMAIL:?Set ALERT_EMAIL to the address that should get alerts}"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
HOST="${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
API="https://monitoring.googleapis.com/v3/projects/${PROJECT}"
TOKEN="$(gcloud auth print-access-token)"
call() { curl -sS --fail-with-body -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" "$@"; }

echo "== Uptime check on https://${HOST}/api/health"
CHECK="$(gcloud monitoring uptime list-configs --project "${PROJECT}" \
          --filter="displayName='Throughline health'" --format='value(name)' 2>/dev/null | head -1)"
if [[ -z "${CHECK}" ]]; then
  CHECK="$(gcloud monitoring uptime create "Throughline health" --project "${PROJECT}" \
            --resource-type=uptime-url --resource-labels="host=${HOST},project_id=${PROJECT}" \
            --protocol=https --path=/api/health --period=1 --timeout=10 \
            --matcher-type=contains-string --matcher-content='"ok":true' --format='value(name)')"
fi
CHECK_ID="${CHECK##*/}"
echo "check ${CHECK_ID}"

echo "== Email channel ${ALERT_EMAIL}"
CHANNEL="$(call "${API}/notificationChannels?filter=type%3D%22email%22" \
            | python3 -c "import json,sys; e='${ALERT_EMAIL}'; print(next((c['name'] for c in json.load(sys.stdin).get('notificationChannels',[]) if c.get('labels',{}).get('email_address')==e), ''))")"
if [[ -z "${CHANNEL}" ]]; then
  CHANNEL="$(call -X POST "${API}/notificationChannels" \
              -d "{\"type\":\"email\",\"displayName\":\"Throughline on-call\",\"labels\":{\"email_address\":\"${ALERT_EMAIL}\"}}" \
              | python3 -c "import json,sys; print(json.load(sys.stdin)['name'])")"
fi
echo "channel ${CHANNEL}"

echo "== Alert policy"
EXISTING="$(call "${API}/alertPolicies" | python3 -c "import json,sys; print(any(p.get('displayName')=='Throughline is down' for p in json.load(sys.stdin).get('alertPolicies',[])))")"
if [[ "${EXISTING}" == "True" ]]; then
  echo "exists"
else
  call -X POST "${API}/alertPolicies" -d @- >/dev/null <<JSON
{
  "displayName": "Throughline is down",
  "combiner": "OR",
  "conditions": [{
    "displayName": "Health check failing",
    "conditionThreshold": {
      "filter": "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.label.check_id=\"${CHECK_ID}\" AND resource.type=\"uptime_url\"",
      "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_NEXT_OLDER",
                        "crossSeriesReducer": "REDUCE_COUNT_FALSE", "groupByFields": ["resource.label.*"]}],
      "comparison": "COMPARISON_GT", "thresholdValue": 1, "duration": "300s", "trigger": {"count": 1}
    }
  }],
  "documentation": {"content": "https://${HOST}/api/health is failing from more than one region. Runbook: docs/GUIDE.md (When something goes wrong).", "mimeType": "text/markdown"},
  "notificationChannels": ["${CHANNEL}"]
}
JSON
  echo "created"
fi
echo "Done. Uptime: https://console.cloud.google.com/monitoring/uptime?project=${PROJECT}"
