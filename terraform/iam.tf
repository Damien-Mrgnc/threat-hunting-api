##############################################################################
# IAM.TF — Service Accounts + Permissions + OIDC GitHub Actions
#
# Principe du moindre privilège : chaque service n'a que
# les permissions strictement nécessaires à son fonctionnement.
##############################################################################

##############################################################################
# SERVICE ACCOUNT — Cloud Run
# Utilisé par l'API FastAPI et le Portal pour accéder aux services GCP
##############################################################################

resource "google_service_account" "cloud_run_sa" {
  account_id   = "${local.prefix}-run-sa"
  display_name = "Cloud Run SA — Threat Hunting API"
  description  = "Service Account pour les services Cloud Run (API + Portal)"
  project      = var.project_id
}

# Accès Cloud SQL (connexion à la base de données)
resource "google_project_iam_member" "cloud_run_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

# Accès Secret Manager (lecture des secrets)
resource "google_project_iam_member" "cloud_run_secrets" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

# Accès Cloud Storage (lecture du dataset)
resource "google_project_iam_member" "cloud_run_storage" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

# Écriture de métriques Cloud Monitoring
resource "google_project_iam_member" "cloud_run_monitoring" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

# Écriture de logs Cloud Logging
resource "google_project_iam_member" "cloud_run_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

##############################################################################
# SERVICE ACCOUNT — GitHub Actions (CI/CD)
# Utilisé par le pipeline GitHub Actions pour builder et déployer
##############################################################################

resource "google_service_account" "github_actions" {
  count        = var.github_repo != "" ? 1 : 0
  account_id   = "${local.prefix}-github-sa"
  display_name = "GitHub Actions SA — CI/CD"
  description  = "Service Account pour GitHub Actions (Workload Identity Federation)"
  project      = var.project_id
}

# Déployer sur Cloud Run
resource "google_project_iam_member" "github_run_developer" {
  count   = var.github_repo != "" ? 1 : 0
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.github_actions[0].email}"
}

# Pusher des images dans Artifact Registry
resource "google_project_iam_member" "github_artifact_writer" {
  count   = var.github_repo != "" ? 1 : 0
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.github_actions[0].email}"
}

# Pouvoir lire les secrets (pour les passer à Cloud Run lors du déploiement)
resource "google_project_iam_member" "github_secrets_viewer" {
  count   = var.github_repo != "" ? 1 : 0
  project = var.project_id
  role    = "roles/secretmanager.viewer"
  member  = "serviceAccount:${google_service_account.github_actions[0].email}"
}

# Permettre au SA GitHub d'agir en tant que SA Cloud Run
# (nécessaire pour déployer avec un SA spécifique)
resource "google_service_account_iam_member" "github_impersonate_run_sa" {
  count              = var.github_repo != "" ? 1 : 0
  service_account_id = google_service_account.cloud_run_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_actions[0].email}"
}

##############################################################################
# WORKLOAD IDENTITY FEDERATION — OIDC pour GitHub Actions
#
# Principe : GitHub Actions prouve son identité via un token OIDC signé par
# GitHub. GCP vérifie ce token et accorde les droits sans clé de service.
# → Plus sécurisé qu'une clé JSON stockée dans les secrets GitHub.
##############################################################################

# Pool d'identités Workload Identity
resource "google_iam_workload_identity_pool" "github" {
  count                     = var.github_repo != "" ? 1 : 0
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions Pool"
  description               = "Pool pour l'authentification GitHub Actions via OIDC"
  project                   = var.project_id
}

# Provider OIDC GitHub dans le pool
resource "google_iam_workload_identity_pool_provider" "github" {
  count                              = var.github_repo != "" ? 1 : 0
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub OIDC Provider"
  project                            = var.project_id

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Restreindre à ton dépôt GitHub uniquement
  attribute_condition = "assertion.repository == \"${var.github_repo}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Lier le SA GitHub au Workload Identity Provider
resource "google_service_account_iam_member" "github_workload_identity" {
  count              = var.github_repo != "" ? 1 : 0
  service_account_id = google_service_account.github_actions[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_repo}"
}
