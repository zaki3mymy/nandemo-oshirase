variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "stage_name" {
  description = "Environment name (dev, prod) for resource naming"
  type        = string
}

variable "otel_python_layer_zip_path" {
  description = "Path to the zip of the OTel Python Lambda layer (built by scripts/build-otel-python-layer.py)"
  type        = string
}
