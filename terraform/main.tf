##############################################################################
# MAIN.TF — Provider GCP + configuration globale
##############################################################################

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Optionnel : stocker le state dans GCS (recommandé en équipe)
  # Décommenter une fois le bucket créé manuellement
  # backend "gcs" {
  #   bucket = "threat-hunting-terraform-state"
  #   prefix = "terraform/state"
  # }
}

# --- Provider principal ---
provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# --- Locals : valeurs calculées réutilisables partout ---
locals {
  # Préfixe commun pour nommer toutes les ressources
  prefix = "threat-hunting"

  # URL du registry Artifact Registry (calculée automatiquement)
  registry_url = "${var.region}-docker.pkg.dev/${var.project_id}/${local.prefix}"

  # Images Docker avec tag latest
  api_image    = "${local.registry_url}/api:latest"
  portal_image = "${local.registry_url}/portal:latest"

  # Nom du bucket GCS dataset (généré si non fourni)
  dataset_bucket = var.dataset_bucket_name != "" ? var.dataset_bucket_name : "${var.project_id}-dataset"

  # Labels communs appliqués à toutes les ressources
  common_labels = {
    project     = "threat-hunting-api"
    environment = var.environment
    managed_by  = "terraform"
  }
}
