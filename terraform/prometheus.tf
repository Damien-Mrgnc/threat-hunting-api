##############################################################################
# PROMETHEUS.TF — Cloud Run service Prometheus
#
# Remplace : service "prometheus" (docker-compose.yml)
# Config baked dans l'image (observability/gcp/prometheus.yml)
# Données éphémères (Cloud Run stateless) — acceptable pour usage démo/cours
##############################################################################

resource "google_cloud_run_v2_service" "prometheus" {
  name     = "${local.prefix}-prometheus"
  location = var.region
  project  = var.project_id

  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.cloud_run_sa.email

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    timeout = "30s"

    containers {
      name  = "prometheus"
      image = "${local.registry_url}/prometheus:latest"

      ports {
        container_port = 9090
      }

      resources {
        limits = {
          cpu    = "0.5"
          memory = "256Mi"
        }
        cpu_idle = true
      }
    }

    labels = local.common_labels
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

resource "google_cloud_run_v2_service_iam_member" "prometheus_public" {
  location = google_cloud_run_v2_service.prometheus.location
  project  = var.project_id
  name     = google_cloud_run_v2_service.prometheus.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
