##############################################################################
# ARTIFACT_REGISTRY.TF — Registry Docker privé GCP
#
# Remplace : Docker Hub public ou images locales
# Avantages :
#   - Intégré à IAM GCP (contrôle d'accès précis)
#   - Scan de vulnérabilités automatique
#   - Accès rapide depuis Cloud Run (même réseau GCP)
##############################################################################

resource "google_artifact_registry_repository" "threat_hunting" {
  repository_id = local.prefix
  project       = var.project_id
  location      = var.region
  format        = "DOCKER"
  description   = "Registry Docker privé — Threat Hunting API"

  labels = local.common_labels

  # Activer le scan de vulnérabilités sur les images pushées
  # (nécessite d'activer l'API containerscanning.googleapis.com)
  # docker_config {
  #   immutable_tags = false
  # }
}


