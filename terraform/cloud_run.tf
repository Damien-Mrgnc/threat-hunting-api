##############################################################################
# CLOUD_RUN.TF — Services Cloud Run (API FastAPI + Portal)
#
# Remplace :
#   - service "api" (FastAPI ×3 replicas) dans docker-compose.yml
#   - service "portal" (FastAPI docs) dans docker-compose.yml
#
# Avantages vs Docker Compose :
#   - Scaling automatique 0→10 instances selon la charge
#   - Pas de gestion de serveur
#   - Restart automatique sur crash
#   - Connexion Cloud SQL via Unix Socket (plus sécurisé que TCP)
##############################################################################

##############################################################################
# SERVICE CLOUD RUN — API FastAPI
##############################################################################

resource "google_cloud_run_v2_service" "api" {
  name     = "${local.prefix}-api"
  location = var.region
  project  = var.project_id

  # Rendre le service accessible publiquement (via le Load Balancer)
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    # --- Service Account ---
    service_account = google_service_account.cloud_run_sa.email

    # --- Scaling ---
    scaling {
      # paused=true → 0 instances (aucun coût, cold start ~2s)
      # paused=false → api_min_instances (3 par défaut, toujours chaud)
      min_instance_count = var.paused ? 0 : var.api_min_instances
      max_instance_count = var.api_max_instances
    }

    # --- Timeout ---
    timeout = "60s" # Timeout des requêtes (la génération de rapports peut prendre du temps)

    # --- VPC : accès au réseau privé (Cloud SQL, Redis) ---
    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY" # Seul le trafic vers IPs privées passe par le VPC
    }

    # --- Conteneur principal API (doit être en premier — Cloud Run exige le port en premier) ---
    containers {
      name  = "api"
      image = local.api_image

      # Démarrer après PgBouncer
      depends_on = ["pgbouncer"]

      # Port d'écoute (Cloud Run injecte PORT=8080 automatiquement)
      ports {
        container_port = 8080
      }

      # --- Ressources ---
      resources {
        limits = {
          cpu    = var.api_cpu
          memory = var.api_memory
        }
        cpu_idle          = false
        startup_cpu_boost = true
      }

      # --- Variables d'environnement (non-sensibles) ---
      env {
        name  = "ALGORITHM"
        value = "HS256"
      }
      env {
        name  = "ACCESS_TOKEN_EXPIRE_MINUTES"
        value = "30"
      }
      env {
        name  = "DATASET_PATH"
        value = "gs://${local.dataset_bucket}/UNSW-NB15.csv"
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }

      # DATABASE_URL pointe vers PgBouncer (localhost) — avec mot de passe (SCRAM-SHA-256)
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url_local.secret_id
            version = "latest"
          }
        }
      }

      # --- Secrets depuis Secret Manager ---
      env {
        name = "SECRET_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.jwt_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "REDIS_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.redis_url.secret_id
            version = "latest"
          }
        }
      }

      # Health checks désactivés pendant le déploiement initial (secrets pas encore configurés)
      # À réactiver après l'étape 7 (configuration des secrets)
    }

    # --- Conteneur PgBouncer (sidecar) ---
    # Transaction pooling : multiplexe les connexions vers Cloud SQL
    # L'API se connecte à localhost:5432 (PgBouncer) au lieu de 10.1.0.3:5432 directement
    containers {
      name  = "pgbouncer"
      image = "edoburu/pgbouncer:latest"

      resources {
        limits = {
          cpu    = "0.25"
          memory = "128Mi"
        }
        cpu_idle = true
      }

      env {
        name  = "POOL_MODE"
        value = "transaction"
      }
      env {
        name  = "MAX_CLIENT_CONN"
        value = "100"
      }
      env {
        name  = "DEFAULT_POOL_SIZE"
        value = "10"
      }
      env {
        name  = "AUTH_TYPE"
        value = "scram-sha-256"
      }
      env {
        name  = "SERVER_RESET_QUERY"
        value = "DISCARD ALL"
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.pgbouncer_dsn.secret_id
            version = "latest"
          }
        }
      }

      # Requis par Cloud Run quand un autre conteneur utilise depends_on
      startup_probe {
        tcp_socket {
          port = 5432
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 5
      }
    }

    # --- Labels pour identifier les révisions ---
    labels = local.common_labels
  }

  # Attendre que les dépendances soient prêtes
  depends_on = [
    google_vpc_access_connector.connector,
    google_service_networking_connection.private_vpc_connection,
    google_secret_manager_secret.database_url,
    google_secret_manager_secret.database_url_local,
    google_secret_manager_secret.jwt_secret,
    google_secret_manager_secret.redis_url,
    google_project_iam_member.cloud_run_secrets,
  ]

  lifecycle {
    # Ne pas recréer le service si l'image change (géré par le CI/CD)
    ignore_changes = [
      template[0].containers[0].image,
    ]
  }
}

##############################################################################
# SERVICE CLOUD RUN — Portal (Documentation FastAPI)
##############################################################################

resource "google_cloud_run_v2_service" "portal" {
  name     = "${local.prefix}-portal"
  location = var.region
  project  = var.project_id

  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.cloud_run_sa.email

    scaling {
      min_instance_count = 0 # Cold start OK pour la doc (trafic rare)
      max_instance_count = 3
    }

    timeout = "30s"

    containers {
      name  = "portal"
      image = local.portal_image

      ports {
        container_port = 8088
      }

      resources {
        limits = {
          cpu    = "0.5"
          memory = "256Mi"
        }
        cpu_idle = true # Économie de coûts : CPU = 0 quand pas de requête
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
    }

    labels = local.common_labels
  }

  depends_on = [google_vpc_access_connector.connector]

  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

##############################################################################
# IAM PUBLIC — Rendre les services Cloud Run accessibles sans authentification
# (Le Load Balancer ou les utilisateurs directs peuvent accéder)
##############################################################################

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  location = google_cloud_run_v2_service.api.location
  project  = var.project_id
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "portal_public" {
  location = google_cloud_run_v2_service.portal.location
  project  = var.project_id
  name     = google_cloud_run_v2_service.portal.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
