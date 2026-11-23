variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "stage_name" {
  description = "Environment name (dev, prod) for resource naming"
  type        = string
}

variable "otel_instrumentations_layer_zip_path" {
  description = "Path to the zip of the Lambda layer with the OTel instrumentations missing from the community layer (built by scripts/build-otel-instrumentations-layer.py)"
  type        = string
}
