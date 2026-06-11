#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${MPP_BOT_TOKEN_FILE:?Set MPP_BOT_TOKEN_FILE to the bot account token JSON}"

REGION="${GCP_REGION:-europe-west1}"
SERVICE="${MPP_BOT_SERVICE:-mpp-bot}"
QUEUE="${MPP_BOT_QUEUE:-mpp-forecasts}"
SECRET="${MPP_BOT_SECRET:-mpp-bot-oauth}"
SERVICE_ACCOUNT_NAME="${MPP_BOT_SERVICE_ACCOUNT_NAME:-mpp-bot-runtime}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${GCP_PROJECT_ID}"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudtasks.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com

PROJECT_NUMBER="$(gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectNumber)')"
CLOUD_TASKS_AGENT="service-${PROJECT_NUMBER}@gcp-sa-cloudtasks.iam.gserviceaccount.com"

gcloud iam service-accounts describe "${SERVICE_ACCOUNT}" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "${SERVICE_ACCOUNT_NAME}" --display-name="MPP bot runtime"

gcloud secrets describe "${SECRET}" >/dev/null 2>&1 \
  || gcloud secrets create "${SECRET}" --replication-policy=automatic
gcloud secrets versions add "${SECRET}" --data-file="${MPP_BOT_TOKEN_FILE}"
gcloud secrets add-iam-policy-binding "${SECRET}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding "${SECRET}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretVersionAdder"
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/cloudtasks.enqueuer"
gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/iam.serviceAccountUser"
gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT}" \
  --member="serviceAccount:${CLOUD_TASKS_AGENT}" \
  --role="roles/iam.serviceAccountUser"

gcloud tasks queues describe "${QUEUE}" --location="${REGION}" >/dev/null 2>&1 \
  || gcloud tasks queues create "${QUEUE}" --location="${REGION}" \
    --max-concurrent-dispatches=2 --max-dispatches-per-second=1

gcloud run deploy "${SERVICE}" \
  --source=. \
  --region="${REGION}" \
  --service-account="${SERVICE_ACCOUNT}" \
  --no-allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=${GCP_PROJECT_ID},MPP_BOT_TOKEN_SECRET=${SECRET},CLOUD_TASKS_LOCATION=${REGION},CLOUD_TASKS_QUEUE=${QUEUE},MPP_BOT_TASK_SERVICE_ACCOUNT=${SERVICE_ACCOUNT},MPP_BOT_ALLOW_WRITE=false"

SERVICE_URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --format='value(status.url)')"
gcloud run services update "${SERVICE}" \
  --region="${REGION}" \
  --update-env-vars="MPP_BOT_SERVICE_URL=${SERVICE_URL}"
gcloud run services add-iam-policy-binding "${SERVICE}" \
  --region="${REGION}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/run.invoker"

if gcloud scheduler jobs describe "${SERVICE}-planner" --location="${REGION}" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "${SERVICE}-planner" \
    --location="${REGION}" \
    --schedule="17 */6 * * *" \
    --uri="${SERVICE_URL}/plan" \
    --http-method=POST \
    --oidc-service-account-email="${SERVICE_ACCOUNT}" \
    --oidc-token-audience="${SERVICE_URL}"
else
  gcloud scheduler jobs create http "${SERVICE}-planner" \
    --location="${REGION}" \
    --schedule="17 */6 * * *" \
    --uri="${SERVICE_URL}/plan" \
    --http-method=POST \
    --oidc-service-account-email="${SERVICE_ACCOUNT}" \
    --oidc-token-audience="${SERVICE_URL}"
fi

echo "Deployed ${SERVICE_URL} in dry-run mode."
echo "Smoke test: gcloud scheduler jobs run ${SERVICE}-planner --location=${REGION}"
echo "Enable writes only after reviewing Cloud Run logs:"
echo "gcloud run services update ${SERVICE} --region=${REGION} --update-env-vars=MPP_BOT_ALLOW_WRITE=true"
