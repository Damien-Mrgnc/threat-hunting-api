# TD — Threat Hunting API sur GCP : Guide de reproduction complet

> Ce document explique **pas à pas** comment reproduire ce projet de zéro, avec le raisonnement derrière chaque choix technique. L'objectif est que tu puisses le refaire seul sans chercher ailleurs.

---

## Table des matières

1. [Présentation du projet](#1-présentation-du-projet)
2. [Architecture globale](#2-architecture-globale)
3. [Prérequis](#3-prérequis)
4. [Structure du projet](#4-structure-du-projet)
5. [Base de données PostgreSQL](#5-base-de-données-postgresql)
6. [API FastAPI](#6-api-fastapi)
7. [Machine Learning — Détection d'attaques](#7-machine-learning--détection-dattaques)
8. [Threat Intelligence — AbuseIPDB](#8-threat-intelligence--abuseipdb)
9. [Observabilité — Prometheus + Grafana](#9-observabilité--prometheus--grafana)
10. [Environnement local — Docker Compose](#10-environnement-local--docker-compose)
11. [CI/CD — GitHub Actions](#11-cicd--github-actions)
12. [Infrastructure GCP — Terraform IaC](#12-infrastructure-gcp--terraform-iac)
13. [Déploiement GCP complet step by step](#13-déploiement-gcp-complet-step-by-step)
14. [Choix techniques expliqués](#14-choix-techniques-expliqués)
15. [Problèmes fréquents et solutions](#15-problèmes-fréquents-et-solutions)

---

## 1. Présentation du projet

### Qu'est-ce que c'est ?

Une **plateforme de threat hunting** production-grade hébergée sur GCP. Elle ingère des événements réseau (format UNSW-NB15), les analyse avec un modèle ML RandomForest, les enrichit avec l'API AbuseIPDB, expose le tout via une API REST sécurisée, et se déploie automatiquement via CI/CD.

### Pourquoi ce projet pour un portfolio DevSecOps ?

| Compétence | Comment elle est démontrée |
|------------|---------------------------|
| Cloud GCP | Cloud Run, Cloud SQL, Memorystore, VPC, Secret Manager |
| IaC | Terraform 14 fichiers .tf couvrant toute l'infra |
| CI/CD sécurisé | GitHub Actions avec 5 security gates |
| SAST / SCA / Container scan | Bandit, pip-audit, Trivy, Checkov |
| Sécurité applicative | JWT, bcrypt, rate limiting, parameterized SQL |
| ML appliqué à la sécu | RandomForest sur 700K événements réseau réels |
| Observabilité | Prometheus + Grafana + 10 alertes de sécurité |
| API sécurisée | FastAPI + Pydantic v2 + SlowAPI |

---

## 2. Architecture globale

```
Internet
    │
    ▼
[Cloud Load Balancer]  ← HTTPS, SSL termination
    │
    ▼
[Cloud Run — API FastAPI]  ← autoscale 1-10 instances
    │  │
    │  └─[Sidecar PgBouncer]  ← connection pooling vers Cloud SQL
    │
    ├──► [Cloud SQL PostgreSQL 15]  ← réseau privé VPC (pas d'IP publique)
    │       └── network_events, jobs, users
    │
    ├──► [Memorystore Redis 6]  ← cache recherches (TTL 30s) + threat intel (TTL 24h)
    │
    └──► [AbuseIPDB API]  ← enrichissement threat intelligence externe

[GitHub Actions CI]
    ├── Bandit (SAST Python)
    ├── pip-audit (CVE dépendances)
    ├── Trivy (CVE image Docker)
    ├── Checkov (misconfigs Terraform)
    └── pytest (tests intégration)

[GitHub Actions CD]  ← déclenché manuellement
    ├── Build image Docker → Artifact Registry
    └── Deploy → Cloud Run

[Local Dev — Docker Compose]
    ├── API × 3 replicas
    ├── PostgreSQL 15
    ├── Redis
    ├── Nginx (reverse proxy + TLS)
    ├── Prometheus
    └── Grafana
```

---

## 3. Prérequis

### Outils à installer

```bash
# Python 3.12+
python --version  # 3.12.x

# Docker Desktop
docker --version  # 24+
docker compose version  # 2.x

# Terraform
terraform --version  # >= 1.7.0

# Git
git --version

# Google Cloud SDK
gcloud --version
```

### Comptes nécessaires

- **GitHub** — hébergement du code + Actions CI/CD
- **Google Cloud Platform** — compte avec facturation activée (nécessaire pour Cloud SQL et Memorystore, pas de free tier)
- **AbuseIPDB** — compte gratuit pour la clé API (1000 requêtes/jour)

### Dataset UNSW-NB15

Télécharger depuis : https://research.unsw.edu.au/projects/unsw-nb15-dataset

Fichier attendu : `data/UNSW-NB15.csv` (concaténation des 4 fichiers CSV, ~700 000 lignes, pas de header)

---

## 4. Structure du projet

```
threat-hunting-api/
├── .github/
│   └── workflows/
│       ├── ci.yml          ← CI : 5 security gates
│       └── cd.yml          ← CD : build + deploy Cloud Run (manuel)
├── .gitignore
├── api/                    ← Code source de l'API (contexte Docker)
│   ├── main.py             ← Point d'entrée FastAPI
│   ├── requirements.txt
│   ├── pytest.ini          ← Config pytest (pythonpath)
│   ├── core/
│   │   ├── database.py     ← SQLAlchemy engine + session
│   │   ├── security.py     ← JWT + bcrypt
│   │   ├── auth.py         ← Dépendances FastAPI (get_current_user)
│   │   ├── observability.py← Métriques Prometheus
│   │   └── redis.py        ← Connexion Redis
│   ├── routers/
│   │   ├── auth.py         ← POST /auth/token
│   │   ├── events.py       ← GET /events/search, /stats, /top
│   │   ├── detect.py       ← POST /detect (ML)
│   │   ├── reports.py      ← Génération rapports async
│   │   ├── jobs.py         ← Suivi jobs background
│   │   └── system.py       ← GET /health, /metrics, /config
│   ├── services/
│   │   ├── threat_intel.py ← AbuseIPDB check_ip()
│   │   └── reporting.py    ← Génération rapports JSON
│   ├── ml/
│   │   └── model.pkl       ← Modèle entraîné (commité en git)
│   └── tests/
│       └── test_integration.py
├── db/
│   ├── schema.sql          ← DDL : tables + seed users
│   └── seed.py             ← Chargement UNSW-NB15 en DB
├── docker/
│   ├── Dockerfile.api      ← Image production Cloud Run (port 8080)
│   └── Dockerfile.*        ← Images pour les autres services
├── infra/
│   ├── docker-compose.yml  ← Stack locale complète
│   ├── .env                ← Variables locales (non commité)
│   └── nginx/
│       ├── nginx.conf
│       └── certs/          ← TLS auto-signé (non commité)
├── ml/
│   └── train.py            ← Script d'entraînement du modèle
├── observability/
│   ├── prometheus.yml
│   ├── prometheus_rules.yml← 10 alertes de sécurité
│   └── grafana/
│       ├── datasources/
│       └── dashboards/
│           ├── dashboard.json
│           └── security-dashboard.json
├── terraform/              ← IaC GCP complet (14 fichiers)
│   ├── main.tf
│   ├── variables.tf
│   ├── cloud_run.tf
│   ├── cloud_sql.tf
│   ├── memorystore.tf
│   ├── vpc.tf
│   ├── iam.tf
│   ├── secrets.tf
│   └── ...
└── data/
    └── UNSW-NB15.csv       ← Non commité (.gitignore)
```

---

## 5. Base de données PostgreSQL

### Pourquoi PostgreSQL ?

PostgreSQL est le standard industrie pour les workloads analytiques. Il supporte les vues matérialisées (aggregations pré-calculées), les index partiels, et s'intègre nativement à Cloud SQL.

### Schema (`db/schema.sql`)

```sql
-- Table principale : événements réseau
CREATE TABLE network_events (
  id        BIGSERIAL PRIMARY KEY,
  ts        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  srcip     TEXT,
  dstip     TEXT,
  proto     TEXT,
  service   TEXT,
  sbytes    BIGINT,
  attack_cat TEXT,
  label     TEXT         -- "0" = normal, "1" = attaque
);

-- Table jobs : suivi des tâches asynchrones
CREATE TABLE jobs (
    job_id       UUID PRIMARY KEY,
    status       TEXT NOT NULL,   -- pending, processing, completed, failed
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    result_path  TEXT,
    error_message TEXT
);

-- Table users : authentification
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'analyst',  -- 'admin' ou 'analyst'
    is_active       BOOLEAN DEFAULT TRUE
);

-- Seed dev-only — NEVER use in production
-- Hash bcrypt rounds=12 pour : Hunt3r$2026!
INSERT INTO users (username, hashed_password, role) VALUES
('admin',   '$2b$12$vzMAk...', 'admin'),
('analyst', '$2b$12$vzMAk...', 'analyst');
```

**Pourquoi UUID pour les jobs ?** Les UUIDs évitent les collisions lors d'insertions parallèles (3 replicas API) et ne révèlent pas l'ordre d'insertion contrairement aux SERIAL.

### Charger les données UNSW-NB15

```bash
# Dans Docker Compose (service api)
docker compose -f infra/docker-compose.yml exec api \
  python /db/seed.py \
  --data /data/UNSW-NB15.csv \
  --dsn postgresql://analyst_user:password@db:5432/threat_hunting_db
```

### Vues matérialisées (optimisation)

Les routes `/events/stats/bytes-by-proto` et `/events/top/attack-categories` font des agrégations sur 700K lignes. Sans optimisation : ~2s. Avec vues matérialisées : <10ms.

```sql
-- Créer après le chargement des données
CREATE MATERIALIZED VIEW mv_network_stats_proto AS
  SELECT proto, SUM(sbytes) AS total_sbytes, COUNT(*) AS event_count
  FROM network_events GROUP BY proto;

CREATE MATERIALIZED VIEW mv_attack_categories AS
  SELECT attack_cat, COUNT(*) AS cnt
  FROM network_events
  WHERE attack_cat IS NOT NULL AND attack_cat <> ''
  GROUP BY attack_cat;

-- Rafraîchissement toutes les 5 minutes (thread background dans main.py)
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_network_stats_proto;
```

---

## 6. API FastAPI

### Pourquoi FastAPI ?

- **Performance** : ASGI async, comparable à NodeJS/Go pour les I/O
- **Validation automatique** : Pydantic v2 valide tous les inputs sans code manuel
- **Docs auto** : Swagger UI et ReDoc générés automatiquement depuis les types Python
- **Standard industrie** : utilisé en prod chez Netflix, Uber, Microsoft

### Point d'entrée (`api/main.py`)

```python
from fastapi import FastAPI
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Threat Hunting API")

# Middleware : ajoute le nom du replica dans chaque réponse
@app.middleware("http")
async def add_process_header(request, call_next):
    response = await call_next(request)
    response.headers["X-API-Replica"] = os.getenv("HOSTNAME", "unknown")
    return response

# Routers
app.include_router(auth.router,    prefix="/auth",    tags=["Security"])
app.include_router(events.router,  prefix="/events",  tags=["Events"])
app.include_router(detect.router)  # prefix défini dans le router (/detect)
app.include_router(system.router)  # /health, /metrics (pas de prefix)
```

**Pourquoi le header `X-API-Replica` ?** Permet de vérifier que le load balancer distribue bien les requêtes entre les 3 replicas. Tu peux le voir dans les réponses curl.

### Connexion base de données (`api/core/database.py`)

```python
from sqlalchemy import create_engine

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,    # Vérifie la connexion avant usage (évite les connexions mortes)
    pool_size=3,           # 3 connexions permanentes par worker
    max_overflow=5,        # 5 connexions supplémentaires si besoin
    pool_timeout=10,       # Timeout d'attente d'une connexion libre
    pool_recycle=300,      # Recrée les connexions toutes les 5min (évite les timeouts réseau)
)
```

**Pourquoi `pool_pre_ping=True` ?** Cloud SQL ferme les connexions inactives après quelques minutes. Sans `pool_pre_ping`, l'API renvoie des erreurs 500 au redémarrage.

### Authentification (`api/core/security.py`)

Le système utilise **JWT (JSON Web Token)** avec signature HMAC-SHA256.

```python
from jose import jwt
import bcrypt

SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_ME_IN_PROD")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def verify_password(plain, hashed):
    """bcrypt compare — résistant aux timing attacks"""
    return bcrypt.checkpw(
        plain.encode('utf-8'),
        hashed.encode('utf-8')
    )

def create_access_token(data: dict, expires_delta):
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + expires_delta
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
```

**Pourquoi bcrypt et pas SHA256 ?** bcrypt est délibérément lent (rounds=12 ≈ 100ms), ce qui rend le brute-force infaisable même avec un GPU. SHA256 serait cracké en quelques secondes.

**Flux d'authentification :**
```
1. POST /auth/token {username, password}
2. SELECT hashed_password FROM users WHERE username = ?
3. bcrypt.checkpw(password, hash)
4. Si OK → JWT signé avec exp = now + 30min
5. Client envoie : Authorization: Bearer <token>
6. FastAPI vérifie la signature et l'expiration à chaque requête
```

### Routes événements (`api/routers/events.py`)

**GET /events/search** — recherche paginée avec cache Redis

```python
@router.get("/search")
def search_events(
    srcip: str = Query(...),        # Paramètre obligatoire
    from_ts: datetime | None = None,
    proto: str | None = None,
    limit: int | None = Query(None),
    offset: int = Query(0, ge=0),
    background: bool = False,       # Mode async si True
    db: Session = Depends(get_db),
    current_user = Depends(get_current_active_analyst),  # JWT requis
):
    # Vérifier le cache Redis (TTL 30s)
    cache_key = f"search:{srcip}:{from_ts}:..."
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    # Requête SQL paramétrée (protection injection SQL)
    query = "SELECT ... FROM network_events WHERE srcip = :srcip"
    # Jamais : WHERE srcip = '" + srcip + "'"  ← injection SQL !
    rows = db.execute(text(query), {"srcip": srcip})
```

**Pourquoi les requêtes paramétrées ?** Si `srcip = "'; DROP TABLE network_events; --"`, une concaténation de string exécuterait la commande. Les paramètres bindés envoient la valeur séparément du SQL.

**Mode background :** Si `?background=true`, la requête est mise en file d'attente comme un job (table `jobs`) et retourne un `job_id`. Le client peut poller `GET /jobs/{job_id}` pour récupérer le résultat.

### Rate limiting (`slowapi`)

```python
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)

# Exemple d'usage sur un endpoint (non implémenté ici — le middleware global suffit)
@router.get("/search")
@limiter.limit("100/minute")
def search_events(request: Request, ...):
    ...
```

SlowAPI s'appuie sur Redis pour compter les requêtes par IP. Sans Redis, il tombe en mode mémoire (non partagé entre replicas).

---

## 7. Machine Learning — Détection d'attaques

### Dataset UNSW-NB15

Créé par l'université UNSW Sydney, ce dataset contient **700 000 flux réseau réels** capturés en 2015, labellisés en 9 catégories d'attaques (DoS, Fuzzers, Exploits...) + trafic normal.

**49 colonnes :** srcip, sport, dstip, dsport, proto, state, dur, sbytes, dbytes, sttl, dttl, sloss, dloss, service, Sload, Dload, Spkts, Dpkts, swin, dwin, stcpb, dtcpb, smeansz, dmeansz, trans_depth, res_bdy_len, Sjit, Djit, Stime, Ltime, Sintpkt, Dintpkt, tcprtt, synack, ackdat, is_sm_ips_ports, ct_state_ttl, ct_flw_http_mthd, is_ftp_login, ct_ftp_cmd, ct_srv_src, ct_srv_dst, ct_dst_ltm, ct_src_ltm, ct_src_dport_ltm, ct_dst_sport_ltm, ct_dst_src_ltm, attack_cat, label

**40 features numériques retenues** (on exclut : srcip, dstip, proto, state, service, Stime, Ltime, attack_cat car nominaux ou inutiles pour la classification binaire).

### Entraînement (`ml/train.py`)

```bash
# Installer les dépendances
pip install scikit-learn joblib pandas numpy

# Lancer l'entraînement
python ml/train.py

# Options disponibles
python ml/train.py --sample 50000    # Réduire pour test rapide
python ml/train.py --n-estimators 200 --max-depth 15  # Plus précis, plus lent
```

**Pipeline sklearn :**

```python
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier

pipeline = Pipeline([
    ("scaler", StandardScaler()),   # Normalise les features (mean=0, std=1)
    ("clf", RandomForestClassifier(
        n_estimators=100,           # 100 arbres de décision
        max_depth=12,               # Profondeur max (évite l'overfitting)
        class_weight="balanced",    # Compense le déséquilibre (97% normal, 3% attaque)
        n_jobs=-1,                  # Utilise tous les CPUs disponibles
        random_state=42,
    )),
])
```

**Pourquoi `class_weight="balanced"` ?** Le dataset est déséquilibré : 3.2% d'attaques, 96.8% de trafic normal. Sans correction, le modèle prédirait "normal" à 97% et serait précis mais inutile. `balanced` pondère les classes inversement proportionnellement à leur fréquence.

**Pourquoi `StandardScaler` ?** RandomForest est théoriquement insensible à l'échelle, mais en pratique le scaler améliore la stabilité numérique et est requis si on veut tester d'autres algorithmes (SVM, régression logistique) sans changer le pipeline.

**Résultats :**
```
ROC-AUC : 0.9994
Accuracy : 99%
Recall attaques : 100% (aucune attaque manquée)
Précision attaques : 86%
```

**Sauvegarde du modèle :**

```python
import joblib

model_artifact = {
    "pipeline": pipeline,
    "feature_columns": FEATURE_COLUMNS,
    "trained_on": len(df),
    "roc_auc": auc,
}
joblib.dump(model_artifact, "api/ml/model.pkl", compress=3)
# compress=3 : réduit la taille sans perte (lz4)
```

Le modèle est commité dans git (`api/ml/model.pkl`) pour être disponible pendant le build Docker en CI/CD.

### Endpoint de détection (`api/routers/detect.py`)

```bash
# Classer un événement réseau
curl -X POST /detect \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"sport": 1390, "dsport": 53, "sbytes": 132, "sttl": 31}'
```

Réponse :
```json
{
  "label": 0,
  "is_attack": false,
  "confidence": 0.9823,
  "model_roc_auc": 0.9994
}
```

**Chargement lazy :** Le modèle n'est chargé en mémoire qu'à la première requête (pas au démarrage). Cela réduit le cold start de Cloud Run.

---

## 8. Threat Intelligence — AbuseIPDB

### Fonctionnement

AbuseIPDB est une base de données collaborative d'IPs malveillantes. L'API gratuite permet 1000 requêtes/jour.

```python
# api/services/threat_intel.py
async def check_ip(ip: str, redis_client) -> dict:

    # 1. Vérifier le cache Redis (TTL 24h = 86400s)
    cache_key = f"threat_intel:{ip}"
    cached = redis_client.get(cache_key)
    if cached:
        return {**json.loads(cached), "cached": True}

    # 2. Appeler AbuseIPDB
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            "https://api.abuseipdb.com/api/v2/check",
            headers={"Key": ABUSEIPDB_API_KEY},
            params={"ipAddress": ip, "maxAgeInDays": 90},
        )

    # 3. Analyser le résultat
    score = resp.json()["data"]["abuseConfidenceScore"]
    is_malicious = score >= 25  # Seuil : ≥ 25% de confiance = malveillant

    # 4. Incrémenter la métrique Prometheus si malveillant
    if is_malicious:
        THREAT_INTEL_HITS_TOTAL.labels(country=country_code).inc()

    # 5. Stocker en cache
    redis_client.setex(cache_key, 86400, json.dumps(result))

    return result
```

**Pourquoi un seuil à 25 ?** AbuseIPDB recommande 25 comme seuil conservateur. À 50, trop de faux négatifs. À 10, trop de faux positifs.

**Pourquoi Redis avec TTL 24h ?** La limite gratuite est 1000 requêtes/jour. Sans cache, une seule IP scanneuse peut épuiser le quota. Avec Redis, chaque IP unique n'est vérifiée qu'une fois par jour.

```bash
# Tester l'endpoint
curl -H "Authorization: Bearer <token>" /detect/intel/1.2.3.4
```

**Variables d'environnement requises :**
- `ABUSEIPDB_API_KEY` — obtenir sur https://www.abuseipdb.com/account/api

---

## 9. Observabilité — Prometheus + Grafana

### Métriques exposées (`api/core/observability.py`)

```python
from prometheus_client import Counter, Histogram, Gauge

# Compteur de requêtes HTTP (par path, method, status)
REQ_COUNT = Counter("http_requests_total", "...", ["path", "method", "status"])

# Histogram des latences (permet de calculer p50, p95, p99)
REQ_LAT = Histogram("http_request_duration_seconds", "...", ["path", "method"])

# Gauge des connexions DB actives
DB_CONN = Gauge("db_pool_checked_out_connections", "...")

# Compteurs sécurité
ML_DETECT_TOTAL = Counter("ml_detections_total", "...", ["label"])
THREAT_INTEL_HITS_TOTAL = Counter("threat_intel_hits_total", "...", ["country"])
```

**Pourquoi un Histogram pour la latence ?** Un Counter ne donne que le total. Un Histogram permet de calculer les percentiles : p95 = "95% des requêtes prennent moins de Xms". C'est la métrique SRE standard.

**Endpoint métriques :** `GET /metrics` retourne le format texte Prometheus (scraped toutes les 5s).

### Alertes de sécurité (`observability/prometheus_rules.yml`)

```yaml
groups:
  - name: security_alerts
    rules:
      # Trop d'erreurs 401 → tentative de brute-force
      - alert: BruteForceAttempt
        expr: |
          sum(increase(http_requests_total{status="401"}[5m])) > 30
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Possible brute-force: >30 tentatives en 5min"

      # Plus de 10 IPs malveillantes en 5min → attaque coordonnée
      - alert: ThreatIntelFlagsSpike
        expr: |
          increase(threat_intel_hits_total[5m]) > 20
        for: 2m
        labels:
          severity: warning

      # Taux d'attaques ML élevé → trafic anormal
      - alert: HighMLAttackDetectionRate
        expr: |
          rate(ml_detections_total{label="1"}[2m]) > 5
        for: 2m
        labels:
          severity: warning
```

### Grafana — Dashboards

Deux dashboards provisionnés automatiquement :
1. **Dashboard principal** — RPS, latences, statuts HTTP, pool DB
2. **Security Dashboard** — authentifications, rate limits, ML détections, threat intel

Les dashboards sont en JSON dans `observability/grafana/dashboards/`. Grafana les charge automatiquement au démarrage via le provisioning.

---

## 10. Environnement local — Docker Compose

### Fichier `.env` (à créer dans `infra/`)

```env
# PostgreSQL
POSTGRES_USER=analyst_user
POSTGRES_PASSWORD=secure_password_123
POSTGRES_DB=threat_hunting_db

# API
DATABASE_URL=postgresql+psycopg://analyst_user:secure_password_123@db:5432/threat_hunting_db
SECRET_KEY=local-dev-secret-key-change-in-prod
REDIS_URL=redis://redis:6379
ABUSEIPDB_API_KEY=your_key_here

# Grafana
GF_SECURITY_ADMIN_PASSWORD=admin
```

**Pourquoi ne pas commiter `.env` ?** Il contient des mots de passe. Le `.gitignore` l'exclut. En prod, ces valeurs viennent de GCP Secret Manager.

### Lancer la stack

```bash
cd infra/

# Premier démarrage (build des images)
docker compose up -d --build

# Vérifier que tout tourne
docker compose ps

# Voir les logs de l'API
docker compose logs -f api

# Charger les données UNSW-NB15 (après démarrage)
docker compose exec api python /db/seed.py \
  --data /data/UNSW-NB15.csv \
  --dsn postgresql://analyst_user:secure_password_123@db:5432/threat_hunting_db

# URLs disponibles
# API :      http://localhost/api
# Grafana :  http://localhost/grafana
# Prometheus: http://localhost/prometheus
```

### Architecture Docker Compose

```yaml
services:
  db:        # PostgreSQL 15 — données persistées dans volume Docker
  api:       # FastAPI — 3 replicas (deploy.replicas: 3)
  nginx:     # Reverse proxy — distribue vers les 3 replicas, TLS
  redis:     # Cache — pas de persistance (données éphémères)
  prometheus:# Scrape /metrics toutes les 5s
  grafana:   # Dashboards — connexion auto à Prometheus
  adminer:   # UI web pour administrer PostgreSQL
```

**Pourquoi 3 replicas API localement ?** Reproduire le comportement Cloud Run et tester que la session JWT (sans état) fonctionne entre replicas. Si le token est stocké en mémoire d'un seul process, les autres replicas rejettent les requêtes.

### Dockerfile API (`docker/Dockerfile.api`)

```dockerfile
FROM python:3.12-slim

# Installer libpq (requis par psycopg pour PostgreSQL)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copier requirements AVANT le code (cache Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY . .

# Port Cloud Run (8080, pas 8000)
ENV PORT=8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
```

**Pourquoi copier `requirements.txt` en premier ?** Docker cache les layers. Si le code change mais pas les dépendances, Docker réutilise le layer pip install (gain de 2-3min en CI).

**Pourquoi `python:3.12-slim` ?** L'image `slim` fait ~130MB vs ~900MB pour `python:3.12`. En Cloud Run, l'image est téléchargée à chaque cold start.

---

## 11. CI/CD — GitHub Actions

### CI — Security Gates (`.github/workflows/ci.yml`)

Déclenché sur chaque push vers `main` ou `develop`.

#### Job 1 : SAST avec Bandit

```yaml
- name: Run Bandit (Python SAST)
  run: |
    bandit -r api/ -ll -x api/tests/ \
      --format json \
      --output bandit-report.json || true
```

- `-ll` : signaler uniquement les sévérités MEDIUM et HIGH
- `-x api/tests/` : exclure les tests (les mocks créent des faux positifs)
- `|| true` : ne pas bloquer le CI si Bandit trouve des issues (on uploade le rapport quand même)

**Ce que Bandit détecte :** injections SQL construites par concaténation, usage de `subprocess.shell=True`, secrets hardcodés, algorithmes cryptographiques faibles.

#### Job 2 : Audit des dépendances avec pip-audit

```yaml
- name: Run pip-audit
  run: |
    pip-audit -r api/requirements.txt \
      --format json \
      --output pip-audit-report.json || true
```

pip-audit compare `requirements.txt` contre la base CVE de PyPA. Si une dépendance a une vulnérabilité connue, elle est reportée.

#### Job 3 : Scan container avec Trivy

```yaml
- name: Build Docker image
  run: docker build -t threat-hunting-api:ci-scan -f docker/Dockerfile.api ./api

- name: Run Trivy
  uses: aquasecurity/trivy-action@master
  with:
    image-ref: threat-hunting-api:ci-scan
    format: sarif
    output: trivy-results.sarif
    severity: CRITICAL,HIGH
    ignore-unfixed: true
    exit-code: "0"   # soft-fail : les findings vont dans GitHub Security tab

- name: Upload SARIF to GitHub Security tab
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: trivy-results.sarif
```

**Pourquoi `exit-code: 0` (soft-fail) ?** Les packages OS Debian ont souvent des CVE sans fix upstream. Bloquer le CI sur ces CVE non-patchables n'apporte rien. Les résultats sont toujours visibles dans `Security → Code scanning`.

**SARIF** = Static Analysis Results Interchange Format. Format standard JSON pour les résultats de security scanning. GitHub l'interprète et l'affiche dans l'onglet Security.

#### Job 4 : Scan IaC avec Checkov

```yaml
- name: Run Checkov on Terraform
  uses: bridgecrewio/checkov-action@master
  with:
    directory: terraform/
    framework: terraform
    output_format: sarif
    soft_fail: true
```

Checkov vérifie les fichiers Terraform contre 1000+ règles de sécurité : chiffrement activé sur Cloud SQL ? Accès public désactivé ? VPC correctement configuré ?

#### Job 5 : Tests d'intégration

```yaml
services:
  postgres:
    image: postgres:15
    env:
      POSTGRES_USER: analyst_user
      POSTGRES_PASSWORD: test_password
      POSTGRES_DB: threat_hunting_db

  redis:
    image: redis:6

steps:
  - name: Apply DB schema
    run: psql -h localhost -U analyst_user -d threat_hunting_db -f db/schema.sql

  - name: Run pytest
    env:
      DATABASE_URL: postgresql+psycopg://analyst_user:test_password@localhost:5432/threat_hunting_db
      REDIS_URL: redis://localhost:6379
      SECRET_KEY: ci-test-secret-key
    working-directory: api
    run: pytest tests/ -v
```

GitHub Actions lance des containers PostgreSQL et Redis comme services annexes. L'API en test s'y connecte via les variables d'environnement.

**Pourquoi `TestClient` et non `httpx.Client(base_url="http://localhost:8000")` ?**

`TestClient` de FastAPI démarre l'application en **mémoire** (ASGI in-process). Pas besoin de lancer un vrai serveur. `httpx.Client` vers localhost requiert un serveur uvicorn en cours d'exécution — ce qui n'est pas le cas en CI.

```python
# CORRECT — in-process, aucun serveur requis
from fastapi.testclient import TestClient
from main import app
client = TestClient(app)

# INCORRECT en CI — serveur non démarré
import httpx
client = httpx.Client(base_url="http://localhost:8000")
```

### CD — Deploy to Cloud Run (`.github/workflows/cd.yml`)

Déclenché **manuellement** (via `workflow_dispatch`) — nécessite une infra GCP déployée.

```yaml
on:
  workflow_dispatch:   # Manuel uniquement

steps:
  - name: Authenticate to GCP
    uses: google-github-actions/auth@v2
    with:
      credentials_json: ${{ secrets.GCP_SA_KEY }}

  - name: Build and push to Artifact Registry
    env:
      IMAGE: ${{ vars.GAR_REGION }}-docker.pkg.dev/${{ vars.GCP_PROJECT_ID }}/threat-hunting/api
    run: |
      docker build -t $IMAGE:${{ github.sha }} -t $IMAGE:latest \
        -f docker/Dockerfile.api ./api
      docker push $IMAGE:${{ github.sha }}
      docker push $IMAGE:latest

  - name: Deploy to Cloud Run
    run: |
      gcloud run deploy threat-hunting-api \
        --image="$IMAGE:${{ github.sha }}" \
        --region="${{ vars.GCP_REGION }}" \
        --platform=managed

  - name: Smoke test
    run: |
      URL=$(gcloud run services describe threat-hunting-api --format="value(status.url)")
      STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$URL/health")
      [ "$STATUS" = "200" ] || exit 1
```

**Secrets GitHub requis :**
- `GCP_SA_KEY` : contenu JSON complet du compte de service GCP

**Variables GitHub requises :**
- `GCP_PROJECT_ID` : ID du projet GCP
- `GCP_REGION` : `europe-west1`
- `GAR_REGION` : `europe-west1`

---

## 12. Infrastructure GCP — Terraform IaC

### Ressources créées

| Fichier | Ressource GCP | Description |
|---------|--------------|-------------|
| `vpc.tf` | VPC + Subnet + VPC Connector | Réseau privé isolé |
| `cloud_sql.tf` | Cloud SQL PostgreSQL 15 | Base de données managée |
| `memorystore.tf` | Memorystore Redis 6 | Cache managé |
| `cloud_run.tf` | 2 services Cloud Run | API + Portal |
| `artifact_registry.tf` | Artifact Registry | Registry Docker privé |
| `secrets.tf` | Secret Manager | Stockage sécurisé des mots de passe |
| `iam.tf` | Service Accounts + IAM | Permissions minimales |
| `load_balancer.tf` | Cloud Load Balancer | HTTPS + SSL |
| `storage.tf` | GCS Bucket | Stockage dataset |

### Fichier principal (`terraform/main.tf`)

```hcl
terraform {
  required_version = ">= 1.7.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  # Backend GCS (recommandé en équipe, commenter pour solo)
  # backend "gcs" {
  #   bucket = "threat-hunting-terraform-state"
  #   prefix = "terraform/state"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  prefix       = "threat-hunting"
  registry_url = "${var.region}-docker.pkg.dev/${var.project_id}/${local.prefix}"
  api_image    = "${local.registry_url}/api:latest"
  common_labels = {
    project    = "threat-hunting-api"
    managed_by = "terraform"
  }
}
```

### Cloud Run avec sidecar PgBouncer (`terraform/cloud_run.tf`)

```hcl
resource "google_cloud_run_v2_service" "api" {
  template {
    # Scaling automatique 0-10 instances
    scaling {
      min_instance_count = var.paused ? 0 : 1
      max_instance_count = 10
    }

    # Réseau privé (accès Cloud SQL et Redis sans IP publique)
    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    # Conteneur principal : API FastAPI
    containers {
      name  = "api"
      image = local.api_image
      ports { container_port = 8080 }
      depends_on = ["pgbouncer"]  # Attendre PgBouncer

      # Secrets injectés comme variables d'environnement
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url_local.secret_id
            version = "latest"
          }
        }
      }
    }

    # Sidecar PgBouncer : pooling de connexions
    containers {
      name  = "pgbouncer"
      image = "edoburu/pgbouncer:latest"
      env { name = "POOL_MODE"        value = "transaction" }
      env { name = "MAX_CLIENT_CONN"  value = "100" }
      env { name = "DEFAULT_POOL_SIZE" value = "10" }
    }
  }
}
```

**Pourquoi PgBouncer comme sidecar ?** Cloud SQL PostgreSQL supporte ~100 connexions simultanées. Avec 10 instances Cloud Run × 8 workers chacun = 80 connexions. PgBouncer en mode `transaction` multiplexe les connexions : 80 clients → 10 vraies connexions DB.

### VPC Privé (`terraform/vpc.tf`)

```hcl
# Cloud SQL n'a PAS d'IP publique — accessible uniquement via le VPC privé
resource "google_sql_database_instance" "main" {
  settings {
    ip_configuration {
      ipv4_enabled    = false  # Pas d'IP publique !
      private_network = google_compute_network.vpc.id
    }
  }
}
```

**Pourquoi pas d'IP publique sur Cloud SQL ?** Si Cloud SQL avait une IP publique, n'importe qui sur Internet pourrait tenter de se connecter (brute-force du mot de passe). Sans IP publique, seules les ressources dans le même VPC peuvent y accéder.

### Secret Manager (`terraform/secrets.tf`)

```hcl
# Créer le secret (le contenant)
resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "jwt-secret-key"
  replication { auto {} }
}

# La valeur est ajoutée manuellement (jamais dans Terraform !)
# gcloud secrets versions add jwt-secret-key --data-file=- <<< "$(openssl rand -base64 32)"
```

**Pourquoi ne pas mettre les valeurs de secrets dans Terraform ?** Le fichier `.tfstate` contiendrait les secrets en clair. Si le state est commité ou partagé, les secrets fuient. Terraform crée la structure, les valeurs sont injectées via gcloud CLI.

---

## 13. Déploiement GCP complet step by step

### Étape 1 — Créer le projet GCP

```bash
# Créer le projet
gcloud projects create threat-hunting-api-2026 --name="Threat Hunting API"

# Définir le projet par défaut
gcloud config set project threat-hunting-api-2026

# Activer la facturation (obligatoire pour Cloud SQL et Memorystore)
# Faire via la console GCP → Billing

# Activer les APIs nécessaires
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  redis.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  vpcaccess.googleapis.com \
  servicenetworking.googleapis.com \
  cloudresourcemanager.googleapis.com
```

### Étape 2 — Créer le compte de service GitHub Actions

```bash
# Créer le SA
gcloud iam service-accounts create github-actions-deployer \
  --display-name="GitHub Actions Deployer"

# Attribuer les rôles
PROJECT_ID="threat-hunting-api-2026"
SA="github-actions-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" \
  --role="roles/iam.serviceAccountUser"

# Générer la clé JSON → coller dans GitHub Secrets comme GCP_SA_KEY
gcloud iam service-accounts keys create key.json \
  --iam-account="${SA}"
cat key.json  # Copier ce contenu entier dans GitHub Secret GCP_SA_KEY
rm key.json   # Supprimer immédiatement après !
```

### Étape 3 — Appliquer Terraform

```bash
cd terraform/

# Créer terraform.tfvars (non commité)
cat > terraform.tfvars << EOF
project_id   = "threat-hunting-api-2026"
region       = "europe-west1"
zone         = "europe-west1-b"
db_password  = "$(openssl rand -base64 24)"
environment  = "production"
EOF

# Initialiser Terraform
terraform init

# Vérifier le plan (lire attentivement avant apply)
terraform plan

# Appliquer (peut prendre 10-15 min)
terraform apply
```

### Étape 4 — Injecter les secrets dans Secret Manager

```bash
PROJECT_ID="threat-hunting-api-2026"
DB_PASS=$(terraform output -raw db_password)
REDIS_IP=$(terraform output -raw redis_host)

# JWT Secret
openssl rand -base64 32 | \
  gcloud secrets versions add jwt-secret-key \
  --project=$PROJECT_ID --data-file=-

# DATABASE_URL (via PgBouncer sur localhost dans le container)
echo "postgresql+psycopg://analyst_user:${DB_PASS}@localhost:5432/threat_hunting_db" | \
  gcloud secrets versions add database-url-local \
  --project=$PROJECT_ID --data-file=-

# REDIS_URL
echo "redis://${REDIS_IP}:6379" | \
  gcloud secrets versions add redis-url \
  --project=$PROJECT_ID --data-file=-
```

### Étape 5 — Construire et pousser l'image Docker

```bash
REGION="europe-west1"
PROJECT_ID="threat-hunting-api-2026"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/threat-hunting/api"

# Authentifier Docker vers Artifact Registry
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Build et push
docker build -t $IMAGE:latest -f docker/Dockerfile.api ./api
docker push $IMAGE:latest
```

### Étape 6 — Appliquer le schema DB sur Cloud SQL

```bash
# Télécharger Cloud SQL Proxy
curl -o cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.8.0/cloud-sql-proxy.linux.amd64
chmod +x cloud-sql-proxy

# Connexion sécurisée via IAM (pas besoin d'IP publique)
./cloud-sql-proxy threat-hunting-api-2026:europe-west1:threat-hunting-db &

# Appliquer le schema
PGPASSWORD=$DB_PASS psql -h 127.0.0.1 -U analyst_user -d threat_hunting_db \
  -f db/schema.sql
```

### Étape 7 — Déployer Cloud Run

```bash
gcloud run deploy threat-hunting-api \
  --image="${IMAGE}:latest" \
  --region="europe-west1" \
  --platform=managed \
  --project=$PROJECT_ID

# Vérifier
URL=$(gcloud run services describe threat-hunting-api \
  --region=europe-west1 --format="value(status.url)")
curl "$URL/health"
# {"status": "ok"}
```

---

## 14. Choix techniques expliqués

### Pourquoi FastAPI et non Flask/Django ?

| Critère | FastAPI | Flask | Django |
|---------|---------|-------|--------|
| Performance | ASGI async | WSGI sync | WSGI sync |
| Validation | Pydantic v2 intégré | Manuelle | Forms Django |
| Docs auto | Swagger + ReDoc | Plugin tiers | Plugin tiers |
| Cloud Run | Excellent (1 worker) | OK | Overkill |

### Pourquoi RandomForest et non un réseau de neurones ?

- **Explicabilité** : RandomForest donne l'importance de chaque feature. Un réseau de neurones est une boîte noire.
- **Performance** : ROC-AUC 0.9994 sur UNSW-NB15 — les réseaux de neurones n'apportent pas de gain significatif sur ce dataset tabulaire.
- **Taille** : Le modèle fait 0.5MB. Un réseau de neurones ferait 50MB+ (cold start Cloud Run).
- **Inférence** : ~1ms par prédiction. Aucun GPU requis.

### Pourquoi Redis pour le cache et non memcache ?

Redis supporte les structures de données complexes (sets, sorted sets, hashes) et la persistance optionnelle. Pour ce projet, on utilise `setex` (string avec TTL) — Redis et Memcache sont équivalents pour ce cas. Redis est choisi car c'est la solution managée disponible sur GCP (Memorystore Redis), et la même instance sert à la fois le cache et le rate limiting SlowAPI.

### Pourquoi Prometheus + Grafana et non Cloud Monitoring ?

Prometheus/Grafana est le standard open-source DevOps : portable, gratuit, utilisé partout. Cloud Monitoring est excellent mais vendor-locked et coûteux. Un recruteur reconnaît Prometheus/Grafana immédiatement.

### Pourquoi le modèle ML est commité en git ?

En ML production, les modèles sont généralement stockés dans un model registry (MLflow, Vertex AI). Ici, le modèle (0.5MB) est commité pour simplifier le CI/CD : l'image Docker l'inclut directement via `COPY . .`. En production réelle, le CD pipeline téléchargerait le modèle depuis GCS avant le build.

---

## 15. Problèmes fréquents et solutions

### `ModuleNotFoundError: No module named 'main'` en pytest

**Cause :** pytest ne sait pas que `api/` est dans le Python path.

**Solution :** Créer `api/pytest.ini` :
```ini
[pytest]
pythonpath = .
testpaths = tests
```

### `httpx.ConnectError: Connection refused` en CI

**Cause :** Les tests utilisent `httpx.Client(base_url="http://localhost:8000")` mais aucun serveur n'est démarré en CI.

**Solution :** Utiliser `TestClient` de FastAPI :
```python
from fastapi.testclient import TestClient
from main import app
client = TestClient(app)
```

### `KeyError: 'label'` avec pandas 3.x dans train.py

**Cause :** `groupby("label").apply()` en pandas 3.0 exclut la colonne groupby du résultat.

**Solution :** Remplacer par `train_test_split` avec stratify :
```python
from sklearn.model_selection import train_test_split
labels = pd.to_numeric(df["label"], errors="coerce").fillna(0).astype(int)
_, df = train_test_split(df, test_size=sample_size, random_state=42, stratify=labels)
```

### `UnicodeEncodeError` avec les caractères `─` ou `…` sur Windows

**Cause :** Windows utilise cp1252 par défaut, qui ne supporte pas les caractères Unicode box-drawing.

**Solution :** Remplacer `─` par `-` et `…` par `...` dans les `print()`.

### Cloud SQL : connexions épuisées

**Symptôme :** Erreurs `too many connections` après scaling.

**Solution :** Ajouter PgBouncer en mode `transaction` (déjà dans `cloud_run.tf`). Réduire `pool_size` dans SQLAlchemy si nécessaire.

### Trivy : exit code 1 bloque le CI pour des CVE OS non patchables

**Solution :** Passer `exit-code: "0"` (soft-fail). Les CVE restent visibles dans l'onglet Security → Code scanning de GitHub.

### `pool_pre_ping=True` : connexions perdues après inactivité

Sans `pool_pre_ping`, Cloud SQL ferme les connexions inactives > quelques minutes. La prochaine requête obtient une connexion morte et plante. `pool_pre_ping=True` fait un `SELECT 1` avant chaque usage pour détecter et recréer les connexions mortes.

---

*Document généré le 2026-04-09 — Projet threat-hunting-api par Damien-Mrgnc*
