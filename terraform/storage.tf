##############################################################################
# STORAGE.TF — Bucket GCS pour le dataset UNSW-NB15
#
# Utilisé par : Cloud Run API (variable d'env DATASET_PATH)
# Format : gs://[bucket]/UNSW-NB15.csv
#
# Le bucket est créé ici, mais le fichier CSV doit être uploadé manuellement :
#   gsutil cp data/UNSW-NB15.csv gs://[PROJECT_ID]-dataset/UNSW-NB15.csv
##############################################################################

resource "google_storage_bucket" "dataset" {
  name          = local.dataset_bucket
  project       = var.project_id
  location      = var.region
  force_destroy = true # Permet terraform destroy sans vider le bucket manuellement

  # Pas de versioning nécessaire pour un dataset statique
  versioning {
    enabled = false
  }

  # Accès uniforme au niveau bucket (pas d'ACL par objet)
  uniform_bucket_level_access = true

  labels = local.common_labels
}

# Donner accès en lecture au service account Cloud Run
resource "google_storage_bucket_iam_member" "dataset_reader" {
  bucket = google_storage_bucket.dataset.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}
