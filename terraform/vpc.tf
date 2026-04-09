##############################################################################
# VPC.TF — Réseau privé VPC + subnets + VPC Connector pour Cloud Run
#
# POURQUOI un VPC privé ?
# Cloud Run ne peut pas accéder directement à Cloud SQL ou Memorystore
# sans passer par un réseau privé. Le VPC Connector fait le pont.
##############################################################################

# --- VPC Principal ---
resource "google_compute_network" "vpc" {
  name                    = "${local.prefix}-vpc"
  auto_create_subnetworks = false # On crée nos propres subnets
  description             = "VPC privé pour la stack Threat Hunting"
}

# --- Subnet Principal (Cloud Run, Cloud SQL, Redis) ---
resource "google_compute_subnetwork" "main" {
  name          = "${local.prefix}-subnet"
  ip_cidr_range = "10.0.0.0/24" # 254 adresses disponibles
  region        = var.region
  network       = google_compute_network.vpc.id

  # Activer les logs VPC Flow pour l'audit
  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# --- Plage d'IP privée pour les services managés (Cloud SQL, Redis) ---
# GCP réserve cette plage pour les services internes
resource "google_compute_global_address" "private_ip_range" {
  name          = "${local.prefix}-private-ip-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16 # 10.1.0.0/16
  network       = google_compute_network.vpc.id
  address       = "10.1.0.0"
}

# --- Peering VPC ↔ Services Managés GCP (Cloud SQL, Redis) ---
resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]
}

# --- Subnet dédié au VPC Connector ---
resource "google_compute_subnetwork" "connector_subnet" {
  name          = "${local.prefix}-connector-subnet"
  ip_cidr_range = "10.9.0.0/28"
  region        = var.region
  network       = google_compute_network.vpc.id
}

# --- VPC Connector : permet à Cloud Run d'accéder au VPC privé ---
# Cloud Run est "serverless" et n'est pas dans le VPC par défaut
# Ce connector crée un tunnel entre Cloud Run et notre VPC
resource "google_vpc_access_connector" "connector" {
  name          = "${local.prefix}-conn"
  region        = var.region
  machine_type  = "e2-micro"
  min_instances = 2
  max_instances = 10

  subnet {
    name       = google_compute_subnetwork.connector_subnet.name
    project_id = var.project_id
  }

  depends_on = [google_compute_subnetwork.connector_subnet]

  lifecycle {
    # Le provider Google recalcule network/self_link/state en "known after apply"
    # à chaque plan quand le connector utilise un subnet — ce qui déclenche une
    # destruction inutile. On ignore tous les changements après création initiale.
    ignore_changes = all
  }
}

# --- Règle Firewall : autoriser le trafic interne VPC ---
resource "google_compute_firewall" "allow_internal" {
  name    = "${local.prefix}-allow-internal"
  network = google_compute_network.vpc.id

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "icmp"
  }

  source_ranges = ["10.0.0.0/8"]
  description   = "Trafic interne VPC (Cloud SQL, Redis, services)"
}

# --- Règle Firewall : autoriser Health Checks du Load Balancer ---
resource "google_compute_firewall" "allow_health_checks" {
  name    = "${local.prefix}-allow-health-checks"
  network = google_compute_network.vpc.id

  allow {
    protocol = "tcp"
    ports    = ["8080", "8088"]
  }

  # IPs GCP des health checkers
  source_ranges = ["130.211.0.0/22", "35.191.0.0/16"]
  description   = "Health checks du Cloud Load Balancer"
}
