##############################################################################
# VARIABLES — Toutes les valeurs configurables de l'infrastructure GCP
# Copier terraform.tfvars.example → terraform.tfvars et renseigner les valeurs
##############################################################################

variable "project_id" {
  description = "ID du projet GCP (ex: threat-hunting-prod)"
  type        = string
}

variable "region" {
  description = "Région GCP principale"
  type        = string
  default     = "europe-west1"
}

variable "zone" {
  description = "Zone GCP principale"
  type        = string
  default     = "europe-west1-b"
}

variable "environment" {
  description = "Environnement (dev, staging, prod)"
  type        = string
  default     = "prod"
}

# --- Base de Données ---

variable "db_instance_name" {
  description = "Nom de l'instance Cloud SQL"
  type        = string
  default     = "threat-hunting-db"
}

variable "db_tier" {
  description = "Tier Cloud SQL (db-g1-small, db-n1-standard-1, ...)"
  type        = string
  default     = "db-g1-small" # 1 vCPU, 1.7 GB RAM — suffisant pour commencer
}

variable "db_name" {
  description = "Nom de la base de données"
  type        = string
  default     = "threat_hunting_db"
}

variable "db_user" {
  description = "Nom d'utilisateur PostgreSQL"
  type        = string
  default     = "analyst_user"
}

# --- Redis ---

variable "redis_memory_size_gb" {
  description = "Taille mémoire Redis en GB"
  type        = number
  default     = 1
}

# --- Cloud Run ---

variable "api_image" {
  description = "Image Docker de l'API (sans tag)"
  type        = string
  default     = ""  # Sera construit depuis var.project_id et var.region
}

variable "api_min_instances" {
  description = "Nombre minimum d'instances Cloud Run API (0 = cold start possible)"
  type        = number
  default     = 3 # 3 instances toujours chaudes = équivalent des 3 répliques Docker Compose
}

variable "api_max_instances" {
  description = "Nombre maximum d'instances Cloud Run API"
  type        = number
  default     = 10
}

variable "api_cpu" {
  description = "CPU alloué par instance Cloud Run API"
  type        = string
  default     = "1"
}

variable "api_memory" {
  description = "Mémoire allouée par instance Cloud Run API"
  type        = string
  default     = "512Mi"
}

# --- Load Balancer ---

variable "domain_name" {
  description = "Nom de domaine pour le certificat TLS managé (laisser vide pour utiliser l'IP directement)"
  type        = string
  default     = "" # Ex: "api.threat-hunting.com"
}

# --- GitHub Actions OIDC ---

variable "github_repo" {
  description = "Dépôt GitHub au format owner/repo (ex: monuser/threat-hunting-api)"
  type        = string
  default     = ""
}

variable "github_branch" {
  description = "Branche GitHub autorisée à déployer"
  type        = string
  default     = "main"
}

# --- Stockage ---

variable "dataset_bucket_name" {
  description = "Nom du bucket GCS pour le dataset UNSW-NB15"
  type        = string
  default     = ""  # Sera généré automatiquement si vide
}

# --- Mode économie ---

variable "paused" {
  description = <<-EOT
    Mettre à true pour éteindre les services coûteux sans détruire l'infrastructure.
    - Cloud SQL  : activation_policy = NEVER   (gratuit, seul le stockage est facturé ~1€/mois)
    - Cloud Run  : min_instances = 0           (cold start ~2s, gratuit sans trafic)
    Usage : terraform apply -var="paused=true"   # éteindre
            terraform apply -var="paused=false"  # rallumer
  EOT
  type    = bool
  default = false
}
