#!/usr/bin/env bash
# gcp_resume.sh — Rallumer les services GCP après une pause
#
# Ce que ça fait :
#   - Cloud SQL  : activation_policy = ALWAYS  → instance démarrée (~2 min)
#   - Cloud Run  : min_instances = 3           → 3 instances toujours chaudes
#
# Usage :
#   bash ops/gcp_resume.sh
#   bash ops/gcp_resume.sh --project mon-projet --region europe-west1

set -euo pipefail

TERRAFORM_DIR="$(cd "$(dirname "$0")/../upgrade/terraform" && pwd)"

PROJECT_ID=""
REGION="europe-west1"

while [[ $# -gt 0 ]]; do
  case $1 in
    --project) PROJECT_ID="$2"; shift 2 ;;
    --region)  REGION="$2";     shift 2 ;;
    *) echo "Argument inconnu : $1"; exit 1 ;;
  esac
done

if [[ -z "$PROJECT_ID" ]]; then
  TFVARS="$TERRAFORM_DIR/terraform.tfvars"
  if [[ -f "$TFVARS" ]]; then
    PROJECT_ID=$(grep 'project_id' "$TFVARS" | head -1 | sed 's/.*=\s*"\(.*\)".*/\1/')
  fi
fi

if [[ -z "$PROJECT_ID" ]]; then
  echo "ERREUR : project_id introuvable. Utilisez --project YOUR_PROJECT_ID"
  exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║           RESUME — Rallumage des services GCP       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Projet  : $PROJECT_ID"
echo "  Région  : $REGION"
echo ""

cd "$TERRAFORM_DIR"

# --- Cloud SQL : rallumer ---
echo "▶ Démarrage Cloud SQL (threat-hunting-db)..."
terraform apply \
  -var="paused=false" \
  -target=google_sql_database_instance.threat_db \
  -auto-approve \
  -compact-warnings 2>&1 | tail -5
echo "  ✓ Cloud SQL : activation_policy = ALWAYS"
echo "  ⏱️  Cloud SQL met ~1-2 min à être prêt"

# --- Cloud Run : remettre 3 instances min ---
echo ""
echo "▶ Cloud Run API → 3 instances minimum..."
terraform apply \
  -var="paused=false" \
  -target=google_cloud_run_v2_service.api \
  -auto-approve \
  -compact-warnings 2>&1 | tail -5
echo "  ✓ Cloud Run API : min_instances = 3"

# --- Attendre que Cloud SQL soit prêt ---
echo ""
echo "▶ Attente que Cloud SQL soit prêt..."
INSTANCE_NAME="threat-hunting-db"
MAX_WAIT=120  # secondes max
WAITED=0
while true; do
  STATUS=$(gcloud sql instances describe "$INSTANCE_NAME" \
    --project="$PROJECT_ID" \
    --format='value(state)' 2>/dev/null || echo "UNKNOWN")

  if [[ "$STATUS" == "RUNNABLE" ]]; then
    echo "  ✓ Cloud SQL prêt ! (état : RUNNABLE)"
    break
  fi

  if [[ $WAITED -ge $MAX_WAIT ]]; then
    echo "  ⚠️  Timeout ($MAX_WAIT s) — Cloud SQL pas encore RUNNABLE (état : $STATUS)"
    echo "     Vérifiez manuellement : gcloud sql instances describe $INSTANCE_NAME"
    break
  fi

  echo "  ... état : $STATUS (attente 10s, ${WAITED}s/$MAX_WAIT s max)"
  sleep 10
  WAITED=$((WAITED + 10))
done

# --- Vérification finale ---
echo ""
echo "▶ Vérification de l'API..."
API_URL=$(terraform output -raw cloud_run_api_url 2>/dev/null || echo "")
if [[ -n "$API_URL" ]]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$API_URL/health" 2>/dev/null || echo "000")
  if [[ "$HTTP_CODE" == "200" ]]; then
    echo "  ✓ API répond : $API_URL/health → HTTP $HTTP_CODE"
  else
    echo "  ⚠️  API répond HTTP $HTTP_CODE (normal si Cloud SQL encore en démarrage)"
    echo "     Réessayez dans 1-2 min : curl $API_URL/health"
  fi
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                     RÉSUMÉ                          ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Cloud SQL     : ACTIF    (~30€/mois)               ║"
echo "║  Cloud Run API : 3 min    (~30€/mois)               ║"
echo "║  Redis         : ACTIF    (~35€/mois)               ║"
echo "║  Load Balancer : ACTIF    (~18€/mois)               ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Coût estimé actif : ~113€/mois                     ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Pour mettre en pause : bash ops/gcp_pause.sh       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
if [[ -n "$API_URL" ]]; then
  echo "  URL API : $API_URL"
  LB_IP=$(terraform output -raw load_balancer_ip 2>/dev/null || echo "")
  [[ -n "$LB_IP" ]] && echo "  Load Balancer (HTTPS) : https://$LB_IP"
  echo ""
fi
