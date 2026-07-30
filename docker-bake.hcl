// Docker Bake — builds backend + frontend IN PARALLEL with GHA cache

variable "IMAGE_PREFIX" {
  default = "ghcr.io/netguy001/alphasync"
}
variable "IMAGE_TAG" {
  default = "latest"
}

// Firebase build args for frontend Vite build
variable "VITE_FIREBASE_API_KEY" { default = "" }
variable "VITE_FIREBASE_AUTH_DOMAIN" { default = "" }
variable "VITE_FIREBASE_PROJECT_ID" { default = "" }
variable "VITE_FIREBASE_STORAGE_BUCKET" { default = "" }
variable "VITE_FIREBASE_MESSAGING_SENDER_ID" { default = "" }
variable "VITE_FIREBASE_APP_ID" { default = "" }

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
  args = {
    VITE_FIREBASE_API_KEY              = VITE_FIREBASE_API_KEY
    VITE_FIREBASE_AUTH_DOMAIN          = VITE_FIREBASE_AUTH_DOMAIN
    VITE_FIREBASE_PROJECT_ID           = VITE_FIREBASE_PROJECT_ID
    VITE_FIREBASE_STORAGE_BUCKET       = VITE_FIREBASE_STORAGE_BUCKET
    VITE_FIREBASE_MESSAGING_SENDER_ID  = VITE_FIREBASE_MESSAGING_SENDER_ID
    VITE_FIREBASE_APP_ID               = VITE_FIREBASE_APP_ID
  }
  cache-from = ["type=gha,scope=frontend-v2"]
  cache-to   = ["type=gha,scope=frontend-v2,mode=max"]
}
