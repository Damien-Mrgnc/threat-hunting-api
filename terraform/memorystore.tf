##############################################################################
# MEMORYSTORE.TF — Redis managé sur GCP
#
# Remplace : service "redis" (redis:alpine) dans docker-compose.yml
# Avantages :
#   - Pas de port exposé sur internet
#   - HA automatique (avec tier STANDARD_HA)
#   - Pas de configuration Redis à maintenir
#   - Intégré dans le VPC privé
##############################################################################

resource "google_redis_instance" "cache" {
  name         = "${local.prefix}-cache"
  project      = var.project_id
  region       = var.region
  display_name = "Threat Hunting Cache (Redis)"

  # BASIC = instance unique (suffisant pour notre usage)
  # STANDARD_HA = haute disponibilité avec réplique (prod critique)
  tier = "BASIC"

  memory_size_gb = var.redis_memory_size_gb
  redis_version  = "REDIS_7_2"

  # Placer Redis dans notre VPC privé
  authorized_network = google_compute_network.vpc.id

  # Plage d'IP pour l'instance Redis dans le VPC
  reserved_ip_range = "10.4.0.0/29"

  # Activer RDB pour la persistance (AOF n'est pas supporté directement de cette façon sur google_redis_instance)
  # Les données survivent aux redémarrages
  persistence_config {
    persistence_mode    = "RDB"
    rdb_snapshot_period = "ONE_HOUR"
  }

  # Maintenance planifiée (dimanche 5h)
  maintenance_policy {
    weekly_maintenance_window {
      day = "SUNDAY"
      start_time {
        hours   = 5
        minutes = 0
        seconds = 0
        nanos   = 0
      }
    }
  }

  labels = local.common_labels
}

# --- Stocker l'URL Redis dans Secret Manager ---
# Une fois l'instance créée, son IP sera connue
# On crée un secret "redis-url" avec la valeur complète
resource "google_secret_manager_secret_version" "redis_url_value" {
  secret = google_secret_manager_secret.redis_url.id

  # L'URL Redis au format attendu par l'API FastAPI
  # redis://HOST:PORT (pas de mot de passe sur BASIC tier)
  secret_data = "redis://${google_redis_instance.cache.host}:${google_redis_instance.cache.port}"

  # Mettre à jour si l'instance Redis change
  depends_on = [google_redis_instance.cache]
}
