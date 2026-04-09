##############################################################################
# SECRETS.TF — Secret Manager GCP
#
# IMPORTANT : Terraform crée les ressources Secret Manager (les "boîtes"),
# mais PAS les valeurs (les "secrets" en eux-mêmes).
# Les valeurs doivent être renseignées manuellement après terraform apply
# via : echo -n "valeur" | gcloud secrets versions add NOM --data-file=-
#
# Voir MIGRATION_GCP_GUIDE.md ÉTAPE 3 pour les commandes exactes.
##############################################################################

# --- Service Account pour accéder aux secrets ---
# Cloud Run utilisera ce SA pour lire les secrets
data "google_project" "project" {}

# --- Secret : Mot de passe PostgreSQL ---
resource "google_secret_manager_secret" "db_password" {
  secret_id = "db-password"
  project   = var.project_id

  labels = local.common_labels

  replication {
    auto {}
  }
}

# --- Secret : URL de connexion complète à la DB ---
# Format : postgresql+psycopg://user:pass@host:5432/dbname
resource "google_secret_manager_secret" "database_url" {
  secret_id = "database-url"
  project   = var.project_id

  labels = local.common_labels

  replication {
    auto {}
  }
}

# --- Secret : Clé JWT (signature des tokens d'authentification) ---
resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "jwt-secret-key"
  project   = var.project_id

  labels = local.common_labels

  replication {
    auto {}
  }
}

# --- Secret : URL Redis (Memorystore) ---
# Format : redis://HOST:6379
resource "google_secret_manager_secret" "redis_url" {
  secret_id = "redis-url"
  project   = var.project_id

  labels = local.common_labels

  replication {
    auto {}
  }
}

# --- Secret : DSN PgBouncer → Cloud SQL (format standard postgres://) ---
# Format : postgres://analyst_user:PASSWORD@10.1.0.3:5432/threat_hunting_db
# À remplir : echo -n "postgres://analyst_user:PASS@10.1.0.3:5432/threat_hunting_db" | gcloud secrets versions add pgbouncer-dsn --data-file=- --project=threat-hunting-api-2026
resource "google_secret_manager_secret" "pgbouncer_dsn" {
  secret_id = "pgbouncer-dsn"
  project   = var.project_id

  labels = local.common_labels

  replication {
    auto {}
  }
}

# --- Secret : URL de connexion locale API → PgBouncer (avec mot de passe pour SCRAM) ---
# Format : postgresql+psycopg://user:password@127.0.0.1:5432/dbname
resource "google_secret_manager_secret" "database_url_local" {
  secret_id = "database-url-local"
  project   = var.project_id

  labels = local.common_labels

  replication {
    auto {}
  }
}

##############################################################################
# IAM : Donner accès aux secrets au Service Account Cloud Run
##############################################################################

locals {
  # Liste de tous les secrets à exposer à Cloud Run
  secrets_for_cloud_run = [
    google_secret_manager_secret.db_password.secret_id,
    google_secret_manager_secret.database_url.secret_id,
    google_secret_manager_secret.jwt_secret.secret_id,
    google_secret_manager_secret.redis_url.secret_id,
    google_secret_manager_secret.pgbouncer_dsn.secret_id,
    google_secret_manager_secret.database_url_local.secret_id,
  ]
}

resource "google_secret_manager_secret_iam_member" "cloud_run_secret_access" {
  for_each = toset(local.secrets_for_cloud_run)

  project   = var.project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}
