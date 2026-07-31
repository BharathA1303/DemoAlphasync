// Docker Bake — builds backend + frontend IN PARALLEL with GHA cache

variable "IMAGE_PREFIX" {
  default = "ghcr.io/netguy001/alphasync"
}
variable "IMAGE_TAG" {
  default = "latest"
}

group "default" {
  targets = ["backend", "frontend"]
}

target "backend" {
  context    = "./backend"
  dockerfile = "Dockerfile"
  tags = [
    "${IMAGE_PREFIX}-backend:latest",
    "${IMAGE_PREFIX}-backend:${IMAGE_TAG}",
  ]
  cache-from = ["type=gha,scope=backend"]
  cache-to   = ["type=gha,scope=backend,mode=max"]
}

target "frontend" {
  context    = "./frontend"
  dockerfile = "Dockerfile"
  tags = [
    "${IMAGE_PREFIX}-frontend:latest",
    "${IMAGE_PREFIX}-frontend:${IMAGE_TAG}",
  ]
  cache-from = ["type=gha,scope=frontend-v2"]
  cache-to   = ["type=gha,scope=frontend-v2,mode=max"]
}
