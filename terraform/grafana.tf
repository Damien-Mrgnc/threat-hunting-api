##############################################################################
# GRAFANA.TF — Cloud Run service Grafana
#
# Remplace : service "grafana" (docker-compose.yml)
# Datasources/dashboards baked dans l'image
# PROMETHEUS_URL est l'URL interne du service Cloud Run Prometheus
##############################################################################

resource "google_cloud_run_v2_service" "grafana" {
  name     = "${local.prefix}-grafana"
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
      name  = "grafana"
      image = "${local.registry_url}/grafana:latest"

      ports {
        container_port = 3000
      }

      resources {
        limits = {
          cpu    = "0.5"
          memory = "256Mi"
        }
        cpu_idle = true
      }

      # URL Prometheus (Cloud Run service direct — évite le round-trip LB)
      env {
        name  = "PROMETHEUS_URL"
        value = google_cloud_run_v2_service.prometheus.uri
      }

      env {
        name  = "GF_AUTH_ANONYMOUS_ENABLED"
        value = "false"
      }
    }

    labels = local.common_labels
  }

  depends_on = [google_cloud_run_v2_service.prometheus]

  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

resource "google_cloud_run_v2_service_iam_member" "grafana_public" {
  location = google_cloud_run_v2_service.grafana.location
  project  = var.project_id
  name     = google_cloud_run_v2_service.grafana.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
