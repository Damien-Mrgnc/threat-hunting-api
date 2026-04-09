#!/usr/bin/env bash
# gcp_pause.sh — Éteindre les services GCP coûteux sans détruire l'infrastructure
#
# Ce que ça fait :
#   - Cloud SQL  : activation_policy = NEVER   → instance éteinte, seul le stockage facturé (~1€/mois)
#   - Cloud Run  : min_instances = 0           → aucun coût sans trafic entrant
#
# Ce qui reste actif (coût fixe inévitable) :
#   - Load Balancer : ~18€/mois
#   - Redis Memorystore : ~35€/mois
#
# Coût total en mode pause : ~54€/mois (vs ~105-135€ actif)
#
# Usage :
#   bash ops/gcp_pause.sh
#   bash ops/gcp_pause.sh --project mon-projet --region europe-west1

set -euo pipefail

TERRAFORM_DIR="$(cd "$(dirname "$0")/../upgrade/terraform" && pwd)"

# Valeurs par défaut (overridables en argument)
PROJECT_ID=""
REGION="europe-west1"

# Parser les arguments optionnels
while [[ $# -gt 0 ]]; do
  case $1 in
    --project) PROJECT_ID="$2"; shift 2 ;;
    --region)  REGION="$2";     shift 2 ;;
    *) echo "Argument inconnu : $1"; exit 1 ;;
  esac
done

# Récupérer le project_id depuis terraform.tfvars si non fourni
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
echo "║          PAUSE — Réduction des coûts GCP            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Projet  : $PROJECT_ID"
echo "  Région  : $REGION"
echo ""

# --- Cloud SQL : éteindre ---
echo "▶ Arrêt Cloud SQL (threat-hunting-db)..."
cd "$TERRAFORM_DIR"
terraform apply \
  -var="paused=true" \
  -target=google_sql_database_instance.threat_db \
  -auto-approve \
  -compact-warnings 2>&1 | tail -5
echo "  ✓ Cloud SQL : activation_policy = NEVER (seul le stockage facturé)"

# --- Cloud Run : 0 instances min ---
echo ""
echo "▶ Cloud Run API → 0 instances minimum..."
terraform apply \
  -var="paused=true" \
  -target=google_cloud_run_v2_service.api \
  -auto-approve \
  -compact-warnings 2>&1 | tail -5
echo "  ✓ Cloud Run API : min_instances = 0 (cold start ~2s)"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                     RÉSUMÉ                          ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Cloud SQL     : ÉTEINT   (~1€/mois stockage)       ║"
echo "║  Cloud Run API : 0 min    (gratuit sans trafic)      ║"
echo "║  Redis         : ACTIF    (~35€/mois inévitable)     ║"
echo "║  Load Balancer : ACTIF    (~18€/mois inévitable)     ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Coût estimé en pause : ~54€/mois (vs ~120€ actif)  ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Pour rallumer : bash ops/gcp_resume.sh             ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
