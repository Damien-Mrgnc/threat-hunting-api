##############################################################################
# CLOUD_SQL.TF — PostgreSQL 15 managé sur GCP
#
# Remplace : service "db" (postgres:15-alpine) dans docker-compose.yml
# Avantages :
#   - Pas de maintenance serveur
#   - Backups automatiques quotidiens (7 jours de rétention)
#   - Failover automatique (si availability_type = REGIONAL)
#   - Point-in-time recovery (retour à n'importe quel moment)
#   - IP privée uniquement (pas accessible depuis internet)
##############################################################################

# --- Instance Cloud SQL PostgreSQL 15 ---
resource "google_sql_database_instance" "threat_db" {
  name             = var.db_instance_name
  project          = var.project_id
  database_version = "POSTGRES_15"
  region           = var.region

  # Empêcher la suppression accidentelle en prod
  deletion_protection = true # ← Mettre à false UNIQUEMENT pour terraform destroy

  settings {
    # Tier de la machine : db-g1-small = 1 vCPU shared, 1.7GB RAM
    # Pour plus de charge : db-n1-standard-1 (1 vCPU dédié, 3.75GB)
    tier = var.db_tier

    # ALWAYS = instance active | NEVER = instance éteinte (seul le stockage est facturé)
    # Contrôlé par var.paused : terraform apply -var="paused=true" pour éteindre
    activation_policy = var.paused ? "NEVER" : "ALWAYS"

    # REGIONAL = haute disponibilité avec failover automatique
    # ZONAL    = moins cher, pas de failover automatique
    availability_type = "ZONAL" # Utiliser REGIONAL pour une vraie prod

    disk_type       = "PD_SSD"
    disk_size       = 20   # GB — le dataset UNSW-NB15 fait ~160MB, on est large
    disk_autoresize = true # Augmente automatiquement si besoin

    # --- Backups ---
    backup_configuration {
      enabled                        = true
      start_time                     = "03:00" # Backup à 3h du matin
      point_in_time_recovery_enabled = true    # Permet de revenir à n'importe quel moment

      backup_retention_settings {
        retained_backups = 7 # Garder 7 jours de backups
        retention_unit   = "COUNT"
      }
    }

    # --- Réseau : IP privée uniquement ---
    ip_configuration {
      ipv4_enabled    = false # Pas d'IP publique !
      private_network = google_compute_network.vpc.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    # --- Paramètres PostgreSQL ---
    database_flags {
      name  = "max_connections"
      value = "100" # Suffisant pour Cloud Run (pool de connexions)
    }

    database_flags {
      name  = "log_min_duration_statement"
      value = "1000" # Logger les requêtes > 1s
    }

    # --- Maintenance ---
    maintenance_window {
      day          = 7 # Dimanche
      hour         = 4 # 4h du matin
      update_track = "stable"
    }

    user_labels = local.common_labels
  }

  # Cloud SQL dépend du peering VPC pour l'IP privée
  depends_on = [google_service_networking_connection.private_vpc_connection]
}

# --- Base de données ---
resource "google_sql_database" "threat_hunting_db" {
  name     = var.db_name
  instance = google_sql_database_instance.threat_db.name
  project  = var.project_id
  charset  = "UTF8"
}

# --- Utilisateur PostgreSQL ---
# ⚠️ Le mot de passe est lu depuis Secret Manager, pas hardcodé ici
# Il sera défini manuellement (voir ÉTAPE 3 du guide)
resource "google_sql_user" "analyst_user" {
  name     = var.db_user
  instance = google_sql_database_instance.threat_db.name
  project  = var.project_id

  # Mot de passe temporaire — À CHANGER immédiatement après création
  # via : gcloud sql users set-password analyst_user --instance=... --password=...
  password = "CHANGE_ME_AFTER_CREATION"

  lifecycle {
    # Ignorer les changements de mot de passe après la création initiale
    # (on le gère via gcloud CLI, pas Terraform)
    ignore_changes = [password]
  }
}
