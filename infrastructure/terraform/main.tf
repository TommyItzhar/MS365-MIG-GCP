# © Itzhar Olivera Solutions & Strategy — Tom Yair Tommy Itzhar Olivera

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 5.0" }
  }
  backend "gcs" {
    bucket = "itzhar-olivera-tfstate"
    prefix = "migration-platform"
  }
}

variable "project_id" { description = "GCP project ID" }
variable "region"     { default = "us-central1" }
variable "env"        { description = "dev | test | prod" }

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_container_cluster" "migration" {
  name                     = "migration-platform-${var.env}"
  location                 = var.region
  remove_default_node_pool = true
  initial_node_count       = 1

  workload_identity_config { workload_pool = "${var.project_id}.svc.id.goog" }

  addons_config {
    http_load_balancing                  { disabled = false }
    gce_persistent_disk_csi_driver_config { enabled = true }
  }

  release_channel { channel = var.env == "prod" ? "STABLE" : "REGULAR" }
}

resource "google_container_node_pool" "primary" {
  name       = "primary"
  cluster    = google_container_cluster.migration.name
  location   = var.region
  node_count = var.env == "prod" ? 3 : 1

  node_config {
    machine_type = var.env == "prod" ? "n2-standard-4" : "e2-medium"
    disk_size_gb = 50
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    workload_metadata_config { mode = "GKE_METADATA" }
    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }

  autoscaling {
    min_node_count = var.env == "prod" ? 2 : 1
    max_node_count = var.env == "prod" ? 10 : 3
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

resource "google_sql_database_instance" "postgres" {
  name             = "migration-postgres-${var.env}"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier              = var.env == "prod" ? "db-custom-2-8192" : "db-f1-micro"
    availability_type = var.env == "prod" ? "REGIONAL" : "ZONAL"

    backup_configuration {
      enabled                        = var.env != "dev"
      point_in_time_recovery_enabled = var.env == "prod"
      start_time                     = "02:00"
    }

    ip_configuration {
      ipv4_enabled = false
      private_network = google_compute_network.vpc.id
    }
  }

  deletion_protection = var.env == "prod"
}

resource "google_sql_database" "main" {
  name     = "migration"
  instance = google_sql_database_instance.postgres.name
}

resource "google_redis_instance" "cache" {
  name           = "migration-redis-${var.env}"
  memory_size_gb = var.env == "prod" ? 4 : 1
  region         = var.region
  tier           = var.env == "prod" ? "STANDARD_HA" : "BASIC"
  redis_version  = "REDIS_7_2"
}

resource "google_compute_network" "vpc" {
  name                    = "migration-vpc-${var.env}"
  auto_create_subnetworks = true
}

resource "google_storage_bucket" "reports" {
  name     = "${var.project_id}-migration-reports-${var.env}"
  location = var.region
  uniform_bucket_level_access = true
  versioning { enabled = var.env == "prod" }

  lifecycle_rule {
    condition { age = 365 }
    action    { type = "Delete" }
  }
}

output "cluster_name" { value = google_container_cluster.migration.name }
output "postgres_connection_name" { value = google_sql_database_instance.postgres.connection_name }
output "postgres_private_ip" { value = google_sql_database_instance.postgres.private_ip_address }
output "redis_host" { value = google_redis_instance.cache.host }
output "reports_bucket" { value = google_storage_bucket.reports.name }
