##############################################################################
# LOAD_BALANCER.TF — Cloud Load Balancer HTTPS
#
# Remplace : Nginx (service "nginx") dans docker-compose.yml
#
# Architecture :
#   [Internet]
#       ↓ HTTPS (443)
#   [Forwarding Rule] → [HTTPS Proxy] → [URL Map] → [Backend Services]
#                                                           ↓
#                                             [Cloud Run API]   [Cloud Run Portal]
#
# Avantages vs Nginx :
#   - Certificat TLS managé et auto-renouvelé par Google
#   - Distribution globale (Anycast IP)
#   - Pas de serveur à maintenir
#   - WAF Google Cloud Armor intégrable
##############################################################################

# --- IP Publique Globale (Anycast) ---
resource "google_compute_global_address" "lb_ip" {
  name        = "${local.prefix}-lb-ip"
  project     = var.project_id
  description = "IP publique du Cloud Load Balancer"
}

##############################################################################
# BACKENDS — Services Cloud Run exposés au Load Balancer
##############################################################################

# Résoudre les services Cloud Run comme backends
resource "google_compute_region_network_endpoint_group" "prometheus_neg" {
  name                  = "${local.prefix}-prometheus-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.prometheus.name
  }
}

resource "google_compute_region_network_endpoint_group" "grafana_neg" {
  name                  = "${local.prefix}-grafana-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.grafana.name
  }
}

resource "google_compute_backend_service" "prometheus_backend" {
  name     = "${local.prefix}-prometheus-backend"
  project  = var.project_id
  protocol = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.prometheus_neg.id
  }

  log_config {
    enable      = true
    sample_rate = 0.5
  }
}

resource "google_compute_backend_service" "grafana_backend" {
  name     = "${local.prefix}-grafana-backend"
  project  = var.project_id
  protocol = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.grafana_neg.id
  }

  log_config {
    enable      = true
    sample_rate = 0.5
  }
}

resource "google_compute_region_network_endpoint_group" "api_neg" {
  name                  = "${local.prefix}-api-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.api.name
  }
}

resource "google_compute_region_network_endpoint_group" "portal_neg" {
  name                  = "${local.prefix}-portal-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.portal.name
  }
}

# Backend Service pour l'API
resource "google_compute_backend_service" "api_backend" {
  name     = "${local.prefix}-api-backend"
  project  = var.project_id
  protocol = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.api_neg.id
  }

  log_config {
    enable      = true
    sample_rate = 1.0 # Logger 100% des requêtes
  }
}

# Backend Service pour le Portal
resource "google_compute_backend_service" "portal_backend" {
  name     = "${local.prefix}-portal-backend"
  project  = var.project_id
  protocol = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.portal_neg.id
  }

  log_config {
    enable      = true
    sample_rate = 0.5 # Logger 50% pour le portal (moins critique)
  }
}

##############################################################################
# URL MAP — Routing des requêtes selon le chemin (comme nginx.conf)
##############################################################################

resource "google_compute_url_map" "url_map" {
  name            = "${local.prefix}-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.portal_backend.id # Défaut → Portal

  # Routing par chemin (équivalent des "location" dans nginx.conf)
  host_rule {
    hosts        = var.domain_name != "" ? [var.domain_name] : ["*"]
    path_matcher = "main-paths"
  }

  path_matcher {
    name            = "main-paths"
    default_service = google_compute_backend_service.portal_backend.id # Défaut → Portal

    # Tous les chemins en route_rules (GCP n'autorise pas le mélange path_rules/route_rules)
    # Priorité : plus petit = évalué en premier

    # /api/* → API FastAPI avec réécriture de préfixe (/api/events → /events)
    route_rules {
      priority = 10
      match_rules { prefix_match = "/api/" }
      route_action {
        url_rewrite { path_prefix_rewrite = "/" }
      }
      service = google_compute_backend_service.api_backend.id
    }

    # /prometheus/* → Prometheus (pas de réécriture : Prometheus gère son propre --web.route-prefix)
    route_rules {
      priority = 20
      match_rules { prefix_match = "/prometheus/" }
      service = google_compute_backend_service.prometheus_backend.id
    }

    # /grafana/* → Grafana (pas de réécriture : Grafana gère GF_SERVER_SERVE_FROM_SUB_PATH)
    route_rules {
      priority = 30
      match_rules { prefix_match = "/grafana/" }
      service = google_compute_backend_service.grafana_backend.id
    }

    # /interface/* → Portal (SPA Threat Interface)
    route_rules {
      priority = 40
      match_rules { prefix_match = "/interface/" }
      service = google_compute_backend_service.portal_backend.id
    }

    # /docs/* → Portal de documentation
    route_rules {
      priority = 50
      match_rules { prefix_match = "/docs" }
      service = google_compute_backend_service.portal_backend.id
    }

    # /health → API
    route_rules {
      priority = 60
      match_rules { full_path_match = "/health" }
      service = google_compute_backend_service.api_backend.id
    }

    # /metrics → API
    route_rules {
      priority = 70
      match_rules { full_path_match = "/metrics" }
      service = google_compute_backend_service.api_backend.id
    }

    # /auth/* → API
    route_rules {
      priority = 80
      match_rules { prefix_match = "/auth/" }
      service = google_compute_backend_service.api_backend.id
    }
  }
}

# Redirection HTTP → HTTPS (port 80 → 443)
resource "google_compute_url_map" "http_redirect" {
  name    = "${local.prefix}-http-redirect"
  project = var.project_id

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

##############################################################################
# CERTIFICAT TLS — Managé (avec domaine) ou auto-signé (sans domaine / IP only)
##############################################################################

# Certificat managé Google : auto-renouvelé, valide uniquement si domain_name est défini
resource "google_compute_managed_ssl_certificate" "threat_cert" {
  count   = var.domain_name != "" ? 1 : 0
  name    = "${local.prefix}-cert"
  project = var.project_id

  managed {
    domains = [var.domain_name]
  }
}

# Certificat auto-signé : utilisé quand aucun domaine n'est configuré (accès par IP)
# Généré par le provider tls — valide 1 an, accepté avec `curl -k`
resource "tls_private_key" "self_signed" {
  count     = var.domain_name == "" ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "self_signed" {
  count           = var.domain_name == "" ? 1 : 0
  private_key_pem = tls_private_key.self_signed[0].private_key_pem

  subject {
    common_name  = "threat-hunting-api"
    organization = "Threat Hunting API (auto-signé)"
  }

  validity_period_hours = 8760 # 1 an

  allowed_uses = [
    "key_encipherment",
    "digital_signature",
    "server_auth",
  ]
}

resource "google_compute_ssl_certificate" "self_signed" {
  count       = var.domain_name == "" ? 1 : 0
  name_prefix = "${local.prefix}-ss-"
  project     = var.project_id
  private_key = tls_private_key.self_signed[0].private_key_pem
  certificate = tls_self_signed_cert.self_signed[0].cert_pem

  lifecycle {
    create_before_destroy = true
  }
}

##############################################################################
# PROXIES & FORWARDING RULES
##############################################################################

# Proxy HTTPS (port 443)
resource "google_compute_target_https_proxy" "https_proxy" {
  name    = "${local.prefix}-https-proxy"
  project = var.project_id
  url_map = google_compute_url_map.url_map.id

  # Certificat managé si domaine configuré, auto-signé sinon (accès par IP avec curl -k)
  ssl_certificates = var.domain_name != "" ? [
    google_compute_managed_ssl_certificate.threat_cert[0].id
  ] : [
    google_compute_ssl_certificate.self_signed[0].id
  ]
}

# Proxy HTTP (port 80) — uniquement pour la redirection vers HTTPS
resource "google_compute_target_http_proxy" "http_proxy" {
  name    = "${local.prefix}-http-proxy"
  project = var.project_id
  url_map = google_compute_url_map.http_redirect.id
}

# Règle de forwarding HTTPS (port 443)
resource "google_compute_global_forwarding_rule" "https_forwarding_rule" {
  name                  = "${local.prefix}-https-rule"
  project               = var.project_id
  ip_address            = google_compute_global_address.lb_ip.address
  port_range            = "443"
  target                = google_compute_target_https_proxy.https_proxy.id
  load_balancing_scheme = "EXTERNAL"
}

# Règle de forwarding HTTP (port 80) → redirection HTTPS
resource "google_compute_global_forwarding_rule" "http_forwarding_rule" {
  name                  = "${local.prefix}-http-rule"
  project               = var.project_id
  ip_address            = google_compute_global_address.lb_ip.address
  port_range            = "80"
  target                = google_compute_target_http_proxy.http_proxy.id
  load_balancing_scheme = "EXTERNAL"
}
