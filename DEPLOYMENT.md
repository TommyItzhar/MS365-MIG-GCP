# Branching Strategy & Deployment

> © Itzhar Olivera Solutions & Strategy — Tom Yair Tommy Itzhar Olivera

## Three-branch GitOps model

```
feature/* ─► dev ─► test ─► prod
              │       │       │
              ▼       ▼       ▼
          ArgoCD  ArgoCD  ArgoCD
            │       │       │ (manual sync)
            ▼       ▼       ▼
        migration-dev   migration-test   migration-prod
                                 (k8s namespaces)
```

| Branch | Auto-deploy | Approval | DB tier | Replicas | URL |
|--------|------------|----------|---------|----------|-----|
| `dev`  | ✅ on push | none | db-f1-micro | 1 each | migration-dev.itzhar-olivera.com |
| `test` | ✅ on push | PR review | db-f1-micro | 2 each | migration-test.itzhar-olivera.com |
| `prod` | ❌ manual | GitHub Environment + ArgoCD sync | db-custom-2-8192 (HA) | 3+/4+/3+ + HPA | migration.itzhar-olivera.com |

## Promotion flow

1. Developer commits to `feature/x`, opens PR against `dev`
2. PR triggers tests (pytest + npm lint/build)
3. Merge to `dev` → CI builds images, tags `dev-<sha>` → updates dev overlay → ArgoCD auto-syncs
4. Cherry-pick / merge `dev` → `test` for staging validation
5. Merge `test` → `prod` requires GitHub Environment approval; ArgoCD prod app must be manually synced

## ArgoCD bootstrap

```bash
# Install ArgoCD (one-time per cluster)
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Apply Application manifests
kubectl apply -f infrastructure/argocd/applications.yaml

# Get UI password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

## Terraform bootstrap (per environment)

```bash
cd infrastructure/terraform
terraform init
terraform workspace new dev   # repeat for test, prod
terraform apply -var "project_id=itzhar-olivera-prod" -var "env=dev"
```

## Observability

- **Prometheus** scrapes `/metrics` on the backend every 15s
- **Grafana** auto-loads the migration overview dashboard
- **Flower** shows live Celery task queue and worker health
- All logs ship to GCP Cloud Logging (or Loki, optional)

## Local development

```bash
./scripts/quickstart.sh
```

This brings up:
- PostgreSQL 15 + Redis 7 + MinIO
- Flask backend (port 5000) + Celery worker + Flower (port 5555)
- React frontend with HMR (port 3000)
- Grafana (port 3001) + Prometheus (port 9090)
