# Threat Hunting API

A production-grade threat hunting platform deployed on Google Cloud Platform. Combines a secured REST API, SQL/Redis performance optimization, ML-based intrusion detection, threat intelligence enrichment, a full observability stack, and infrastructure-as-code with Terraform.

**Dataset:** [UNSW-NB15](https://research.unsw.edu.au/projects/unsw-nb15-dataset) — 700,000 real network events labeled with attack categories (DoS, Exploits, Reconnaissance, Backdoors…)

---

## Architecture

```
Internet (HTTPS)
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│          Cloud Load Balancer  (Global HTTPS)             │
│                                                          │
│  /            → Portal    Cloud Run                      │
│  /api/*       → API       Cloud Run  (autoscale 1-10)    │
│  /interface/* → Portal    Cloud Run  (SPA)               │
│  /grafana/*   → Grafana   Cloud Run                      │
│  /prometheus/*→ Prometheus Cloud Run                     │
└──────────────────────────────────────────────────────────┘
       │
       ├── Cloud SQL  PostgreSQL 15   (private VPC — 10.1.0.3)
       ├── Memorystore Redis 6        (private VPC — 10.4.0.3)
       └── VPC Connector             (Cloud Run ↔ private resources)
```

All Cloud Run services communicate with Cloud SQL and Redis over a **private VPC** — no database port is ever exposed to the internet.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **API** | Python 3.12, FastAPI, SQLAlchemy, Pydantic v2 |
| **Auth** | JWT (python-jose), bcrypt, SlowAPI rate limiting |
| **Database** | PostgreSQL 15, B-Tree indexes, materialized views |
| **Cache** | Redis 6 (Google Memorystore) |
| **ML Detection** | scikit-learn RandomForestClassifier, joblib |
| **Threat Intel** | AbuseIPDB API (IP reputation, cached 24h in Redis) |
| **Observability** | Prometheus, Grafana (perf + security dashboards), custom metrics |
| **CI/CD** | GitHub Actions — Bandit SAST, pip-audit, Trivy, Checkov, Cloud Run deploy |
| **Infrastructure** | Terraform (IaC), GCP Cloud Run, Cloud SQL, VPC, Secret Manager |
| **Containers** | Docker, Artifact Registry, multi-stage builds |
| **Local dev** | Docker Compose (API × 3 replicas, Nginx, PostgreSQL, Redis, Grafana) |

---

## Security

### CI/CD Security Gates (GitHub Actions)

Every push and pull request runs four automated security checks before any code reaches production:

| Gate | Tool | What it checks |
|------|------|----------------|
| **SAST** | [Bandit](https://bandit.readthedocs.io/) | Python code for hardcoded secrets, injection flaws, insecure functions |
| **Dependency audit** | [pip-audit](https://pypi.org/project/pip-audit/) | Known CVEs in all pinned Python dependencies |
| **Container scan** | [Trivy](https://trivy.dev/) | CVEs in the Docker image (OS packages + Python layers) |
| **IaC scan** | [Checkov](https://www.checkov.io/) | Terraform misconfigurations (open ports, missing encryption, overpermissioned IAM) |

Results are uploaded as SARIF to the **GitHub Security tab** for centralized tracking.

### Cloud (GCP)
- **Private networking** — Cloud SQL and Redis are only reachable within the VPC
- **Secret Manager** — `DATABASE_URL`, `JWT_SECRET_KEY`, `REDIS_URL` stored as GCP secrets, injected at runtime — no credentials in code or environment files
- **Least privilege IAM** — dedicated service account with only the required roles
- **HTTPS enforced** — TLS termination at the Load Balancer level

### Application
- **JWT authentication** — all sensitive endpoints require a valid bearer token
- **Rate limiting** — IP-based throttling via SlowAPI (brute-force and DDoS protection)
- **SQL injection prevention** — SQLAlchemy parameterized queries throughout
- **Input validation** — strict Pydantic v2 schemas on all request bodies and query parameters

### Local (Docker Compose)
- API, PostgreSQL, Redis and Adminer are on an internal Docker network — only Nginx (port 80/443) is exposed to the host
- API runs as 3 replicas behind Nginx for load distribution

---

## ML Threat Detection

A RandomForestClassifier is trained on the UNSW-NB15 dataset to classify network events as **normal (0)** or **attack (1)** in real time.

| Property | Value |
|----------|-------|
| Algorithm | RandomForestClassifier (scikit-learn) |
| Features | 40 numeric flow features (bytes, packets, TTL, jitter, TCP flags…) |
| Training set | 100,000 stratified samples from UNSW-NB15 |
| Typical ROC-AUC | ~0.98 |
| Inference latency | < 5 ms per event |

**Train the model (required before first push):**

```bash
# From the project root
pip install scikit-learn joblib pandas numpy
python ml/train.py
# → Saves model to api/ml/model.pkl (~10 MB)
# → Commit api/ml/model.pkl so it is included in the Docker image
```

**Use the endpoint:**

```bash
TOKEN=$(curl -s -X POST http://localhost/auth/token \
  -d "username=admin&password=secret" | jq -r .access_token)

curl -X POST http://localhost/api/detect \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": 1390, "dsport": 53, "dur": 0.001,
    "sbytes": 132, "dbytes": 164, "sttl": 31, "dttl": 29,
    "Spkts": 2, "Dpkts": 2, "Sload": 500473.9, "Dload": 621800.9
  }'
# → {"label": 0, "is_attack": false, "confidence": 0.97, "model_roc_auc": 0.98}
```

---

## Threat Intelligence

IP addresses are enriched with [AbuseIPDB](https://www.abuseipdb.com/) reputation data. Results are cached in Redis for 24 hours to stay within the free tier (1,000 checks/day).

**Set your API key:**
```bash
# Add to infra/.env (local) or GCP Secret Manager (production)
ABUSEIPDB_API_KEY=your_key_here
```

**Query an IP:**
```bash
curl http://localhost/api/detect/intel/1.2.3.4 \
  -H "Authorization: Bearer $TOKEN"
# → {"ip": "1.2.3.4", "abuse_confidence_score": 100, "is_malicious": true,
#     "total_reports": 847, "country_code": "CN", "cached": false}
```

---

## Performance Results

Tests run from a **Cloud Run Job** on the same GCP internal network (~2ms base latency).
All phases use 100 distinct source IPs to eliminate Redis cache bias.

### `/events/search` — 1,000 requests, concurrency 50

| Phase | RPS | P50 | P95 | P99 | vs Baseline |
|-------|-----|-----|-----|-----|-------------|
| 🐢 Baseline (no index) | 16 req/s | 3,033 ms | 3,896 ms | 5,231 ms | — |
| 🔧 SQL index only | 60 req/s | 743 ms | 1,416 ms | 1,738 ms | **×3.8 RPS / ×4.1 P50** |
| 🚀 Full optimized (+Redis) | 64 req/s | 697 ms | 1,327 ms | 1,671 ms | **×4.1 RPS / ×4.4 P50** |

**Optimizations applied:**
- B-Tree index on `(srcip, ts, proto)` — eliminates full sequential scan on 700K rows
- Materialized view `mv_network_stats_proto` — pre-computed byte aggregations
- Redis cache — sub-10ms responses on repeated queries

### Burst test — 10,000 concurrent requests

| Endpoint | RPS | Success rate | Result |
|----------|-----|-------------|--------|
| `GET /health` (lightweight) | 451 req/s | **99.99%** | ✅ Cloud Run autoscaling validated |
| `GET /events/top/attack-categories` (heavy DB) | 16 req/s | **1.3%** | ⚠️ Expected — `db-g1-small` saturates at 25 connections |

> Full benchmark report: [`upgrade/RAPPORT_PERFORMANCE.md`](upgrade/RAPPORT_PERFORMANCE.md)

---

## Project Structure

```
threat-hunting-api/
├── .github/
│   └── workflows/
│       ├── ci.yml              # Security gates: Bandit · pip-audit · Trivy · Checkov
│       └── cd.yml              # Deploy to Cloud Run on push to main
├── api/                        # FastAPI application
│   ├── core/                   #   database, auth, redis, observability (Prometheus metrics)
│   ├── ml/                     #   model.pkl — pre-trained RandomForest (generate with ml/train.py)
│   ├── routers/                #   events, reports, jobs, auth, system, detect (ML + threat intel)
│   ├── services/               #   reporting, threat_intel (AbuseIPDB)
│   └── tests/                  #   integration tests
├── db/
│   ├── schema.sql              # PostgreSQL schema + seed users
│   ├── optimize.sql            # Indexes + materialized views
│   └── deoptimize.sql          # Rollback script (used by benchmark)
├── docker/
│   ├── Dockerfile.api          # Production API image
│   ├── Dockerfile.seed         # Cloud Run Job — loads UNSW-NB15 from GCS
│   ├── Dockerfile.tests        # Cloud Run Job — performance benchmark suite
│   ├── Dockerfile.prometheus
│   └── Dockerfile.grafana
├── infra/
│   ├── docker-compose.yml      # Local full-stack (API ×3, Nginx, PG, Redis, Grafana)
│   └── nginx/nginx.conf
├── ml/
│   └── train.py                # Training script — RandomForest on UNSW-NB15 (40 features)
├── observability/
│   ├── prometheus.yml          # Local scrape config
│   ├── prometheus_rules.yml    # Alert rules: SLO + security (brute force, rate flood, ML spikes)
│   ├── gcp/prometheus.yml      # GCP scrape config (Cloud Run HTTPS target)
│   └── grafana/
│       └── dashboards/
│           ├── api-dashboard.json       # Performance — golden signals, latency, DB pool
│           └── security-dashboard.json  # Security — auth failures, rate limits, ML detections
├── ops/
│   ├── run_tests_gcp.py        # Orchestrates baseline / optimized / burst phases
│   ├── benchmark.py            # Local benchmark runner
│   ├── burst_test.py           # Concurrent load generator
│   └── toggle_perf.py          # Enable/disable indexes + Redis via API
├── portal/                     # FastAPI portal + SPA serving
├── interface/                  # Threat hunting SPA (HTML/CSS/JS)
└── terraform/                  # Full GCP infrastructure as code
    ├── main.tf                 #   provider config, locals, labels
    ├── vpc.tf                  #   VPC, subnets, VPC connector
    ├── cloud_sql.tf            #   Cloud SQL PostgreSQL 15
    ├── memorystore.tf          #   Redis Memorystore
    ├── cloud_run.tf            #   API + Portal Cloud Run services
    ├── load_balancer.tf        #   Global HTTPS load balancer + URL map
    ├── secrets.tf              #   Secret Manager resources
    ├── iam.tf                  #   Service accounts + IAM roles
    ├── artifact_registry.tf    #   Docker image registry
    └── storage.tf              #   GCS bucket (dataset + results)
```

---

## Local Setup

**Prerequisites:** Docker, Docker Compose

```bash
git clone https://github.com/Damien-Mrgnc/threat-hunting-api.git
cd threat-hunting-api

# 1. Configure environment
cp infra/.env.example infra/.env
# Edit infra/.env with your credentials

# 2. Train the ML model (first time only)
pip install scikit-learn joblib pandas numpy
python ml/train.py          # → api/ml/model.pkl

# 3. Start the full stack
cd infra && docker compose up -d

# 4. Load the UNSW-NB15 dataset
docker compose exec api python /db/seed.py

# 5. Apply SQL optimizations
docker compose exec api psql $DATABASE_URL -f /db/optimize.sql
```

| Service | URL | Credentials |
|---------|-----|-------------|
| Portal | `http://localhost/` | — |
| API Swagger | `http://localhost/api/docs` | — |
| Threat Interface | `http://localhost/interface/` | admin / secret |
| Grafana (performance) | `http://localhost/grafana/d/api-performance` | admin / admin |
| Grafana (security) | `http://localhost/grafana/d/threat-security-v1` | admin / admin |
| Prometheus | `http://localhost/prometheus/` | — |

---

## GCP Deployment

**Prerequisites:** `gcloud` CLI, `terraform` >= 1.7, `docker`, a GCP project with billing enabled

```bash
# 1. Authenticate
gcloud auth login && gcloud auth application-default login

# 2. Configure Terraform
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform.tfvars: project_id, region, db_password

# 3. Build and push Docker images
REGISTRY="<region>-docker.pkg.dev/<project-id>/threat-hunting"
docker build -t $REGISTRY/api:latest -f docker/Dockerfile.api ./api
docker push $REGISTRY/api:latest

# 4. Deploy full infrastructure (~5 min)
cd terraform && terraform init && terraform apply

# 5. Init database (via Cloud SQL Auth Proxy)
./cloud-sql-proxy <project>:<region>:threat-hunting-db &
psql $DATABASE_URL -f db/schema.sql

# 6. Run performance benchmark
gcloud run jobs execute threat-hunting-tests \
  --region=<region> --project=<project-id> --wait
```

### CI/CD Setup (GitHub Actions)

**Secrets** (`Settings → Secrets and variables → Actions`):

| Secret | Description |
|--------|-------------|
| `GCP_SA_KEY` | GCP service account JSON key with `roles/run.admin`, `roles/artifactregistry.writer` |

**Variables** (`Settings → Secrets and variables → Actions → Variables`):

| Variable | Example |
|----------|---------|
| `GCP_PROJECT_ID` | `threat-hunting-api-2026` |
| `GCP_REGION` | `europe-west1` |
| `GAR_REGION` | `europe-west1` |

---

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/auth/token` | — | Get JWT token |
| `GET` | `/health` | — | Health check + replica info |
| `GET` | `/metrics` | — | Prometheus metrics (OpenMetrics) |
| `GET` | `/events/search` | JWT | Search events by source IP (indexed + cached) |
| `GET` | `/events/top/attack-categories` | JWT | Top attack categories |
| `GET` | `/events/stats/bytes-by-proto` | JWT | Traffic volume by protocol (materialized view) |
| `POST` | `/reports/generate` | JWT | Async report generation |
| `GET` | `/reports/{id}` | JWT | Download generated report |
| `POST` | `/config/features` | JWT (admin) | Toggle Redis cache / SQL indexes at runtime |
| `POST` | `/detect` | JWT | **ML** — Classify a network event as normal/attack |
| `GET` | `/detect/model/info` | JWT | **ML** — Model metadata and ROC-AUC score |
| `GET` | `/detect/intel/{ip}` | JWT | **Threat intel** — AbuseIPDB IP reputation check |

Full interactive docs available at `/api/docs` (Swagger UI)

---

## Observability

### Grafana Dashboards

| Dashboard | Panels |
|-----------|--------|
| **API Performance** | RPS, p50/p95/p99 latency, error rate, DB pool saturation |
| **Security** | Auth failures (401), rate limit hits (429), ML attack rate, threat intel flags, error breakdown by endpoint |

### Prometheus Alert Rules

| Alert | Condition | Severity |
|-------|-----------|----------|
| `HighErrorRate` | > 5% of requests return 5xx | critical |
| `SlowQueries` | p99 latency > 2s | warning |
| `DBPoolSaturation` | > 18/20 connections checked out | critical |
| `APIDown` | No metrics received for 30s | critical |
| `BruteForceAttempt` | > 30 auth failures in 5 min | warning |
| `SustainedAuthFailures` | > 10 failures/min for 10 min | critical |
| `RateLimitFlood` | > 60 rate-limit rejections/min | warning |
| `UnauthorizedAdminAccess` | > 10 forbidden (403) in 5 min | warning |
| `HighMLAttackDetectionRate` | ML flags > 5 events/sec as attacks | warning |
| `ThreatIntelFlagsSpike` | > 20 IPs flagged by AbuseIPDB in 5 min | warning |

---

## Identified Limits and Recommended Improvements

| Limit | Root cause | Recommended fix |
|-------|-----------|-----------------|
| Burst DB — 1.3% success on 10K concurrent | `db-g1-small` = 25 connections max | PgBouncer or upgrade to `db-n1-standard-2` |
| `/top/attack-categories` — P50 ~17s | No index on `attack_cat` column | Dedicated materialized view |
| Self-signed TLS certificate | No DNS domain configured | GCP managed certificate (auto-renewed Let's Encrypt) |
| ML model not retrained automatically | Static artifact committed to git | Scheduled retraining Cloud Run Job + GCS model storage |

---

## Documentation

| Document | Content |
|----------|---------|
| [`docs/STACK.md`](docs/STACK.md) | Technology choices and justifications |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Security measures — network, application, secrets |
| [`upgrade/RAPPORT_DEPLOIEMENT.md`](upgrade/RAPPORT_DEPLOIEMENT.md) | Full GCP deployment report — 14 bugs fixed, infrastructure details |
| [`upgrade/RAPPORT_PERFORMANCE.md`](upgrade/RAPPORT_PERFORMANCE.md) | Auto-generated benchmark report — P50/P95/P99 per phase |
| [`upgrade/AMELIORATIONS.md`](upgrade/AMELIORATIONS.md) | Post-deployment improvement roadmap |
