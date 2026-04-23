#!/usr/bin/env bash
# =============================================================================
# RAG-Ops Platform — K3d Cluster Setup Script
# Creates a local multi-node K3s cluster using K3d and deploys all services.
# =============================================================================

set -euo pipefail

CLUSTER_NAME="ragops-cluster"
NAMESPACE="ragops"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success(){ echo -e "${GREEN}[OK]${NC} $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Dependency checks ─────────────────────────────────────────────────────────
check_deps() {
  log "Checking dependencies..."
  for cmd in docker k3d kubectl; do
    command -v "$cmd" >/dev/null 2>&1 || error "$cmd is not installed. Please install it first."
    success "$cmd found: $(command -v $cmd)"
  done
}

# ── Create K3d cluster ────────────────────────────────────────────────────────
create_cluster() {
  log "Creating K3d cluster: $CLUSTER_NAME..."

  if k3d cluster list | grep -q "$CLUSTER_NAME"; then
    warn "Cluster '$CLUSTER_NAME' already exists. Skipping creation."
    return 0
  fi

  k3d cluster create "$CLUSTER_NAME" \
    --agents 2 \
    --servers 1 \
    --port "8000:30800@loadbalancer" \
    --port "9001:30901@loadbalancer" \
    --port "8080:30880@loadbalancer" \
    --port "9090:30909@loadbalancer" \
    --port "3000:30300@loadbalancer" \
    --wait

  success "K3d cluster '$CLUSTER_NAME' created with 1 server + 2 agents"
}

# ── Deploy all manifests ──────────────────────────────────────────────────────
deploy_manifests() {
  log "Deploying Kubernetes manifests..."

  # Namespace + ConfigMap + Secrets
  kubectl apply -f k8s/base/namespace.yaml

  # Wait for namespace
  kubectl wait --for=jsonpath='{.status.phase}'=Active namespace/$NAMESPACE --timeout=30s

  # Storage layer
  kubectl apply -f k8s/storage/minio.yaml
  kubectl apply -f k8s/storage/chromadb.yaml

  # Data layer
  kubectl apply -f k8s/base/postgres.yaml

  # Inference layer
  kubectl apply -f k8s/base/ollama.yaml

  # Application layer
  kubectl apply -f k8s/base/api.yaml

  # Monitoring
  kubectl apply -f k8s/monitoring/monitoring-stack.yaml

  success "All manifests applied"
}

# ── Wait for pods ─────────────────────────────────────────────────────────────
wait_for_pods() {
  log "Waiting for all pods to be ready (this may take a few minutes)..."

  local timeout=300

  for deployment in postgres minio chromadb; do
    log "  Waiting for $deployment..."
    kubectl rollout status deployment/$deployment -n $NAMESPACE --timeout=${timeout}s
    success "  $deployment is ready"
  done

  log "  Waiting for Ollama (model downloads take time)..."
  kubectl rollout status deployment/ollama -n $NAMESPACE --timeout=600s
  success "  Ollama is ready"

  kubectl rollout status deployment/rag-api -n $NAMESPACE --timeout=${timeout}s
  success "  RAG API is ready"
}

# ── Print access info ─────────────────────────────────────────────────────────
print_access_info() {
  echo ""
  echo "═══════════════════════════════════════════════════════════"
  echo "  RAG-Ops Platform — Access URLs"
  echo "═══════════════════════════════════════════════════════════"
  echo "  API Gateway:     http://localhost:8000"
  echo "  API Docs:        http://localhost:8000/docs"
  echo "  MinIO Console:   http://localhost:9001  (admin/minioadmin)"
  echo "  Airflow:         http://localhost:8080  (admin/admin)"
  echo "  Prometheus:      http://localhost:9090"
  echo "  Grafana:         http://localhost:3000  (admin/admin)"
  echo "═══════════════════════════════════════════════════════════"
  echo ""
  echo "  Quick test:"
  echo "    curl http://localhost:8000/health"
  echo "    curl http://localhost:8000/health/ready"
  echo ""
}

# ── Teardown ──────────────────────────────────────────────────────────────────
teardown() {
  warn "Deleting K3d cluster '$CLUSTER_NAME'..."
  k3d cluster delete "$CLUSTER_NAME"
  success "Cluster deleted"
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  case "${1:-up}" in
    up)
      check_deps
      create_cluster
      deploy_manifests
      wait_for_pods
      print_access_info
      ;;
    down)
      teardown
      ;;
    redeploy)
      kubectl delete -f k8s/ --recursive --ignore-not-found=true -n $NAMESPACE
      deploy_manifests
      wait_for_pods
      print_access_info
      ;;
    status)
      kubectl get all -n $NAMESPACE
      ;;
    *)
      echo "Usage: $0 {up|down|redeploy|status}"
      exit 1
      ;;
  esac
}

main "$@"
