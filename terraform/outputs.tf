##############################################################################
# OUTPUTS.TF — Valeurs importantes affichées après terraform apply
#
# Ces valeurs sont utiles pour :
#   - Configurer le DNS (load_balancer_ip)
#   - Tester l'API (cloud_run_api_url)
#   - Mettre à jour les secrets (cloud_sql_private_ip)
#   - Configurer GitHub Actions (github_* outputs)
##############################################################################

# --- Réseau ---
output "vpc_id" {
  description = "ID du VPC créé"
  value       = google_compute_network.vpc.id
}

output "vpc_connector_id" {
  description = "ID du VPC Connector (utilisé par Cloud Run)"
  value       = google_vpc_access_connector.connector.id
}

# --- Load Balancer ---
output "load_balancer_ip" {
  description = "⭐ IP publique du Load Balancer — Créer un enregistrement DNS A pointant ici"
  value       = google_compute_global_address.lb_ip.address
}

output "api_url_https" {
  description = "URL HTTPS de l'API (via Load Balancer)"
  value       = var.domain_name != "" ? "https://${var.domain_name}" : "https://${google_compute_global_address.lb_ip.address}"
}

# --- Cloud Run ---
output "cloud_run_api_url" {
  description = "URL directe du service Cloud Run API (sans passer par le LB)"
  value       = google_cloud_run_v2_service.api.uri
}

output "cloud_run_portal_url" {
  description = "URL directe du service Cloud Run Portal"
  value       = google_cloud_run_v2_service.portal.uri
}

# --- Cloud SQL ---
output "cloud_sql_instance_name" {
  description = "Nom de l'instance Cloud SQL"
  value       = google_sql_database_instance.threat_db.name
}

output "cloud_sql_private_ip" {
  description = "⭐ IP privée de Cloud SQL — Nécessaire pour configurer le secret DATABASE_URL"
  value       = google_sql_database_instance.threat_db.private_ip_address
  sensitive   = false
}

output "cloud_sql_connection_name" {
  description = "Connection name Cloud SQL (format: project:region:instance)"
  value       = google_sql_database_instance.threat_db.connection_name
}

# --- Redis ---
output "redis_host" {
  description = "Host Redis (Memorystore)"
  value       = google_redis_instance.cache.host
}

output "redis_port" {
  description = "Port Redis (Memorystore)"
  value       = google_redis_instance.cache.port
}

output "redis_url" {
  description = "URL Redis complète"
  value       = "redis://${google_redis_instance.cache.host}:${google_redis_instance.cache.port}"
}

# --- Artifact Registry ---
output "registry_url" {
  description = "URL du registry Artifact Registry"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${local.prefix}"
}

output "api_image_tag" {
  description = "Commande docker build pour l'image API"
  value       = "docker build -t ${local.registry_url}/api:latest ./api"
}

# --- Cloud Storage ---
output "dataset_bucket_url" {
  description = "URL du bucket GCS pour le dataset"
  value       = "gs://${google_storage_bucket.dataset.name}"
}

# --- Service Accounts ---
output "cloud_run_service_account" {
  description = "Email du Service Account Cloud Run"
  value       = google_service_account.cloud_run_sa.email
}

# --- GitHub Actions (OIDC) ---
output "github_workload_identity_provider" {
  description = "⭐ Valeur à copier dans le secret GitHub GCP_WORKLOAD_IDENTITY_PROVIDER"
  value = var.github_repo != "" ? (
    "projects/${data.google_project.project.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github[0].workload_identity_pool_id}/providers/${google_iam_workload_identity_pool_provider.github[0].workload_identity_pool_provider_id}"
  ) : "Non configuré (var.github_repo est vide)"
}

output "github_service_account_email" {
  description = "⭐ Valeur à copier dans le secret GitHub GCP_SERVICE_ACCOUNT"
  value       = var.github_repo != "" ? google_service_account.github_actions[0].email : "Non configuré"
}

# --- Commandes utiles après apply ---
output "next_steps" {
  description = "Étapes à suivre après terraform apply"
  value       = <<-EOT
    ✅ Infrastructure créée avec succès !

    📋 ÉTAPES SUIVANTES :

    1. Renseigner les secrets (si pas encore fait) :
       gcloud secrets versions add db-password --data-file=-
       gcloud secrets versions add jwt-secret-key --data-file=-
       gcloud secrets versions add database-url --data-file=-
       (voir upgrade/DEPLOY_GCP.md Étape 7)

    2. Configurer le mot de passe Cloud SQL :
       gcloud sql users set-password ${var.db_user} \
         --instance=${var.db_instance_name} \
         --password=VOTRE_PASSWORD

    3. Mettre à jour le secret DATABASE_URL avec l'IP Cloud SQL :
       IP Cloud SQL : ${google_sql_database_instance.threat_db.private_ip_address}

    4. Builder et pusher les images Docker :
       docker build -t ${local.registry_url}/api:latest ./api
       docker push ${local.registry_url}/api:latest

    5. Configurer le DNS (si domaine configuré) :
       Créer un enregistrement A : ${var.domain_name != "" ? var.domain_name : "ton-domaine.com"} → ${google_compute_global_address.lb_ip.address}

    6. Tester l'API :
       curl ${google_cloud_run_v2_service.api.uri}/health
  EOT
}
