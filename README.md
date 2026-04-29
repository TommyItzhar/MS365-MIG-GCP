# MS365 → Google Workspace Migration Platform

> **© Itzhar Olivera Solutions & Strategy**
> *by Tom Yair Tommy Itzhar Olivera*

End-to-end orchestration platform for migrating Microsoft 365 environments to Google Cloud / Google Workspace, covering all seven phases from your migration workplan: pre-migration discovery, environment preparation, Intune off-boarding, Google MDM on-boarding, AvePoint Fly migration, cutover, and post-migration cleanup.

## What this platform does

- **Discovers** every device in Intune via Microsoft Graph API (managed devices + Autopilot identities)
- **Lets you select** one device, a filtered set, or all devices for migration actions
- **Executes each step** of the workplan as a Celery-backed task (54 tasks across 7 phases)
- **Off-boards from Intune** — Autopilot deregistration, retire/wipe, AAD removal, managed device deletion
- **Enrolls into Google MDM** — GCPW for Windows, MDM profiles for macOS/iOS/Android, Chrome/ChromeOS policies
- **Triggers AvePoint Fly** migration jobs and polls for completion
- **Performs cutover** — DNS/SPF/DKIM/DMARC validation, mail flow checks
- **Cleans up** — revokes M365 service account, removes app registration, archives GCP credentials

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite + Recharts (UI in white / Microsoft Blue / Google Purple) |
| Backend | Python 3.12 + Flask + Celery |
| Database | PostgreSQL 15 |
| Cache / queue | Redis 7 |
| Object storage | MinIO (S3-compatible) for migration reports |
| Container orchestration | Kubernetes (GKE) |
| GitOps | ArgoCD with `dev`, `test`, `prod` Applications |
| CI/CD | GitHub Actions |
| Observability | Prometheus + Grafana + Flower (Celery) |
| Infrastructure as Code | Terraform |
| Secrets | External Secrets Operator → GCP Secret Manager (recommended) |

## Branching model

```
feature/* → dev (auto-deploy) → test (auto-deploy after review) → prod (manual approval)
```

See `DEPLOYMENT.md` for the full GitOps flow.

## Quick start (local)

```bash
cp .env.example .env
# edit .env with your M365 / Google credentials, then:
./scripts/quickstart.sh
```

This brings up the entire stack:
- UI: http://localhost:3000
- API: http://localhost:5000
- Flower (Celery): http://localhost:5555
- Grafana: http://localhost:3001 (admin/admin)
- Prometheus: http://localhost:9090
- MinIO: http://localhost:9001 (minioadmin/minioadmin)

## Repository layout

```
ms365-gcp-migration/
├── backend/                  Flask API + Celery workers
│   ├── app/
│   │   ├── api/              Blueprints: discovery, devices, migration, tasks_api, health
│   │   ├── core/             Config (dev/test/prod)
│   │   ├── models/           SQLAlchemy: Device, MigrationTask, TaskLog
│   │   └── services/         GraphService, GoogleWorkspaceService, Celery tasks
│   └── tests/                pytest smoke tests
├── frontend/                 React 18 + Vite SPA (the white/blue/purple UI)
├── infrastructure/
│   ├── argocd/               ArgoCD Application manifests (dev/test/prod)
│   ├── grafana/              Provisioning + dashboards + Prometheus config
│   ├── k8s/
│   │   ├── base/             Deployment, ConfigMap, Secret stub, Ingress
│   │   └── overlays/         Kustomize: dev / test / prod
│   └── terraform/            GKE cluster, Cloud SQL, Redis
├── scripts/                  quickstart.sh
├── .github/workflows/        ci-cd.yml (3-branch pipeline)
├── docker-compose.yml        Full local stack
└── DEPLOYMENT.md             GitOps & promotion docs
```

## Migration phases (from workplan)

| # | Phase | Tasks |
|---|-------|-------|
| 1 | Pre-migration | 10 |
| 2 | Environment preparation | 6 |
| 3 | Intune off-boarding | 7 |
| 4 | Google MDM on-boarding | 8 |
| 5 | Migration execution | 9 |
| 6 | Cutover | 6 |
| 7 | Post-migration | 8 |
| **Total** | | **54** |

Every task is seeded into the database via `POST /api/v1/migration/seed` and runnable individually or as a phase-batch from the UI.

## Security notes

- The Azure AD app registration uses Microsoft Graph application permissions (Impersonation/EWS is being deprecated by Microsoft on Oct 1 2026 — this platform uses Graph from day one)
- Google service account uses domain-wide delegation, with a dedicated super admin subject for elevated operations
- Secrets are never committed; Kubernetes manifests reference `migration-secrets` populated by External Secrets Operator
- Production overlay enforces PodDisruptionBudgets and HorizontalPodAutoscalers
- ArgoCD prod app is `automated.prune: false` and `automated.selfHeal: false` — every prod sync is intentional
