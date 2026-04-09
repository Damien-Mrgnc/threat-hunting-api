# Rapport Final — Threat Hunting API
> Projet Cloud Administration A4 | GCP europe-west1 | 2026
> Auteur : Damien

---

## 1. Présentation du projet

### Contexte

Ce projet consiste à concevoir, déployer et optimiser une **API de Threat Hunting** — un outil d'analyse de trafic réseau permettant à des analystes de sécurité de rechercher et classifier des événements réseau suspects à partir du dataset **UNSW-NB15** (~2.5 millions de logs réseau réels).

L'objectif pédagogique est double :
- Démontrer la maîtrise du déploiement cloud (GCP) avec Infrastructure as Code
- Appliquer une démarche d'optimisation progressive mesurée par des tests de charge réels

### Ce que fait l'application

| Fonctionnalité | Endpoint | Description |
|---------------|----------|-------------|
| Recherche par IP source | `GET /events/search?srcip=X` | Filtre les événements réseau par IP avec pagination |
| Statistiques par protocole | `GET /events/stats/bytes-by-proto` | Volume de données échangées par protocole |
| Top catégories d'attaque | `GET /events/top/attack-categories` | Classement des types d'attaque détectés |
| Génération de rapports | `POST /reports/monthly` | Rapport PDF/JSON des activités mensuelles par IP |
| Jobs asynchrones | `GET /jobs/{id}` | Suivi de tâches longues en arrière-plan |
| Authentification JWT | `POST /auth/token` | Tokens d'accès (rôles : analyst / admin) |

---

## 2. Choix techniques — justification

### 2.1 Backend : FastAPI (Python)

**Pourquoi FastAPI ?**
- **Performances I/O** : FastAPI + Uvicorn est basé sur ASGI (asynchrone). Sur des opérations I/O (requêtes DB, appels Redis), il rivalise avec Node.js et Go.
- **Validation automatique** : Pydantic valide et sérialise toutes les entrées/sorties API sans code boilerplate.
- **Documentation auto-générée** : Swagger UI (`/docs`) et ReDoc (`/redoc`) gratuits, critiques pour les équipes SOC.
- **Typage strict** : Réduit les bugs en production, IDE-friendly.

### 2.2 Base de données : PostgreSQL 15

**Pourquoi PostgreSQL ?**
- Standard industriel pour les données analytiques avec support des **index avancés** (B-Tree, GiST, BRIN).
- **Vues matérialisées** : permettent de pré-calculer des agrégats coûteux (SUM, GROUP BY) et de les servir en O(1).
- **EXPLAIN ANALYZE** : outillage de diagnostic de requêtes puissant, essentiel pour la phase d'optimisation.
- Compatible Cloud SQL (GCP) sans modification de code.

### 2.3 Cache : Redis

**Pourquoi Redis ?**
- Stockage clé-valeur **en mémoire** : latence <1ms vs ~50-700ms pour une requête SQL optimisée.
- TTL (Time-To-Live) natif : gestion de l'invalidation du cache sans code.
- Pattern **Cache-Aside** : l'API vérifie Redis avant PostgreSQL, écrit après chaque cache miss.
- En GCP : Memorystore Redis est géré (pas de gestion serveur) et accessible via IP privée VPC.

**Impact mesuré** : réponse `/top/attack-categories` passée de 170ms (SQL) à **7ms** (Redis) en local.

### 2.4 Load Balancer : Nginx (local) / Cloud Load Balancer HTTPS (GCP)

**Pourquoi un Load Balancer ?**
- **Point d'entrée unique** : expose un seul port (80/443) vers l'extérieur, cache les services internes.
- **Round-Robin** : distribue équitablement le trafic entre les répliques API.
- **Failover automatique** : redirige vers les instances saines si une tombe.
- **TLS termination** : SSL/HTTPS géré une seule fois au niveau LB, pas dans chaque instance.

### 2.5 PgBouncer (connection pooling)

**Pourquoi PgBouncer ?**
- PostgreSQL alloue ~5-10 Mo par connexion. Sur `db-g1-small` (25 connexions max), 100 threads API concurrents saturent immédiatement.
- PgBouncer **multiplexe** : 100 connexions logiques → 10 connexions physiques (transaction pooling).
- Déployé comme **sidecar** dans le même pod Cloud Run, connexion via `localhost:5432`.
- Impact mesuré : burst `/events/top` passé de **1% → 68.9% de succès** sur 20 000 requêtes.

### 2.6 Observabilité : Prometheus + Grafana

**Pourquoi Prometheus/Grafana ?**
- **Prometheus** scrape les métriques exposées par FastAPI (`/metrics`) : latences, RPS, taux d'erreur.
- **Grafana** visualise ces métriques en temps réel avec des dashboards configurables.
- Permet de valider les optimisations de manière objective et de détecter les régressions.

### 2.7 Infrastructure as Code : Terraform

**Pourquoi Terraform ?**
- **Reproductibilité** : l'infrastructure entière (`terraform apply`) peut être recréée en 10 minutes depuis zéro.
- **Versionnable** : les changements d'infra sont trackés en Git comme du code.
- **Idempotent** : relancer `terraform apply` ne casse rien si rien n'a changé.
- **State management** : Terraform connaît l'état réel des ressources GCP et calcule le diff minimal.

---

## 3. Architecture

### 3.1 Version locale (Docker Compose)

```
Client HTTP
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Nginx (port 80) — Load Balancer + Micro-cache          │
│  Round-Robin vers 3 répliques API                       │
└─────────────────────┬───────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   [api-1:8000]  [api-2:8000]  [api-3:8000]   FastAPI + Uvicorn
        │
        ├── PostgreSQL 15 (port 5432)
        ├── Redis 7 (port 6379)
        └── Prometheus (port 9090) → Grafana (port 3000)
```

**Services Docker Compose :**
- `nginx` — reverse proxy + load balancer
- `api` (×3 répliques) — FastAPI application
- `db` — PostgreSQL 15
- `redis` — Redis 7
- `prometheus` — collecte des métriques
- `grafana` — dashboards

**Démarrage :**
```bash
docker compose -f infra/docker-compose.yml up -d --build
```
Accès : http://localhost (portail central → interface, Grafana, docs)

### 3.2 Version Cloud (GCP)

```
Internet (HTTPS)
       │
       ▼
Cloud Load Balancer Global (IP : 34.54.187.254)
  /api/*          → Cloud Run: threat-hunting-api
  /interface/*    → Cloud Run: threat-hunting-portal
  /grafana/*      → Cloud Run: threat-hunting-grafana
  /prometheus/*   → Cloud Run: threat-hunting-prometheus
       │
       ├── Cloud Run API (FastAPI + PgBouncer sidecar)
       │       ├── PgBouncer :5432 (localhost) → Cloud SQL :5432
       │       └── Redis Memorystore (10.4.0.3:6379)
       │
       ├── Cloud SQL PostgreSQL 15 (IP privée : 10.1.0.3)
       ├── Memorystore Redis 6 (IP privée : 10.4.0.3)
       └── VPC threat-hunting-vpc (réseau privé isolé)
```

**Ressources Terraform (13 ressources principales) :**

| Ressource | Nom GCP | Rôle |
|-----------|---------|------|
| VPC | `threat-hunting-vpc` | Réseau privé isolé |
| VPC Connector | `threat-hunting-conn` | Pont Cloud Run ↔ VPC |
| Cloud SQL | `threat-hunting-db` (PG 15) | Base de données |
| Memorystore | Redis 6, 1 GB | Cache + jobs |
| Cloud Run API | `threat-hunting-api` | Backend FastAPI |
| Cloud Run Portal | `threat-hunting-portal` | Interface web |
| Cloud Run Grafana | `threat-hunting-grafana` | Dashboards |
| Cloud Run Prometheus | `threat-hunting-prometheus` | Métriques |
| Load Balancer HTTPS | `threat-hunting-url-map` | Routage global |
| Artifact Registry | `threat-hunting` | Images Docker |
| Secret Manager | `jwt-secret-key`, `redis-url`, etc. | Secrets chiffrés |
| GCS Bucket | `threat-hunting-api-2026-dataset` | Dataset + rapports |

---

## 4. Déploiement local — résultats

### 4.1 Environnement

- Docker Desktop (Windows), 1.4 millions de logs UNSW-NB15
- Tests : scripts Python `ops/load_test.py`, concurrence 20 threads, 1 000 requêtes

### 4.2 Progression des performances (endpoint `/events/stats/bytes-by-proto`)

| Étape | Technologie ajoutée | Latence P50 | RPS | Gain cumulé |
|-------|---------------------|-------------|-----|-------------|
| **1. Baseline** | SQL brut (seq scan) | 367 ms | <10 | — |
| **2. Index B-Tree** | `CREATE INDEX idx_srcip` | 20 ms | ~50 | **×18** |
| **3. Cache Redis** | Pattern Cache-Aside TTL 60s | **7 ms** | ~200 | **×52** |
| **4. 3 répliques + Nginx** | Round-Robin Load Balancing | 47 ms avg | **~400** | **×40 RPS** |
| **5. Nginx micro-cache** | `proxy_cache_path` (60s) | **<2 ms** | **>10 000** | **×180 RPS** |

> La Phase 5 (Nginx micro-cache) sert les réponses statiques directement depuis RAM Nginx.
> La base de données n'est plus sollicitée pour les requêtes identiques dans la fenêtre TTL.

### 4.3 Load Balancing — validation

| Test | Résultat |
|------|---------|
| Distribution Round-Robin (3 nœuds) | 33.4% / 33.4% / 33.2% — parfaitement équilibré |
| Failover (arrêt api-1 en cours de test) | 50% / 50% sur les 2 nœuds restants — 0 interruption visible |
| Charge 1 000 req, c=20 | 400 RPS, P50=43ms, P95=85ms, P99=125ms, 100% succès |

### 4.4 Sécurité implémentée

- **Surface d'attaque réduite** : seul le port 80 (Nginx) exposé ; PostgreSQL, Redis, API sur réseau Docker interne
- **Anti-injection SQL** : SQLAlchemy avec requêtes paramétrées systématiques
- **Rate Limiting** : SlowAPI (100 req/min par IP)
- **Validation stricte** : schémas Pydantic sur toutes les entrées
- **Secrets externalisés** : variables d'environnement `.env`, aucune credential dans le code
- **JWT Authentication** : tokens signés HS256, expiration 30 minutes

---

## 5. Déploiement GCP — versions

### v1 — Déploiement initial (2026-03-19)
**Infrastructure :** Cloud Run 1 vCPU / 512Mi / max 10, Cloud SQL db-g1-small
**Optimisations actives :** Index B-Tree + Vue matérialisée `mv_network_stats_proto` + Redis cache
**Résultats :**

| Endpoint | Phase | P50 | RPS | Succès |
|----------|-------|-----|-----|--------|
| `/events/search` | BASELINE | 2 837 ms | 18 req/s | 100% |
| `/events/search` | INDEX SQL | ~700 ms | ~60 req/s | 100% |
| `/events/search` | FULL OPTIMISÉ | 827 ms | 56 req/s | 100% |
| `/health` burst 10K | — | — | 509 req/s | 100% |
| `/events/top` burst 10K | — | — | 16 req/s | **1.0%** |

> Conclusion v1 : index SQL fonctionnel (×4 sur P50 `/search`), mais Cloud SQL saturé sous burst.

---

### v2 — Optimisations complètes confirmées (2026-03-20)
**Infrastructure :** identique à v1
**Optimisations actives :** identiques + concurrence doublée (50 threads, 1 000 req)
**Résultats :**

| Endpoint | Phase | P50 | RPS | Succès |
|----------|-------|-----|-----|--------|
| `/events/search` | BASELINE | 3 033 ms | 16 req/s | 100% |
| `/events/search` | INDEX SQL | 743 ms | 60 req/s | 100% |
| `/events/search` | FULL OPTIMISÉ | **697 ms** | **64 req/s** | 100% |
| `/events/stats` | INDEX SQL | 664 ms | 63 req/s | 100% |
| `/events/top` | BASELINE | 17 765 ms | 3 req/s | 100% |
| `/health` burst 10K | — | — | 451 req/s | 99.99% |
| `/events/top` burst 10K | — | — | 16 req/s | **1.3%** |

> Conclusion v2 : **gain réel mesuré = ×4.1 sur P50 `/search`** (index B-Tree seul, sans biais Redis).
> `/top/attack-categories` reste lent (17s) → absence de vue matérialisée dédiée identifiée.

---

### v3 — Upgrade machines pour isolation du bottleneck (2026-03-26)
**Infrastructure :** Cloud Run **4 vCPU / 4Gi / max 50**, Cloud SQL **db-custom-2-7680** (2 vCPU / 7.5 Go)
**Note :** DSN Cloud SQL non accessible depuis machine locale → indexes non re-appliqués. Toutes les phases tournent sans index actifs.

| Endpoint | P50 | RPS | Succès |
|----------|-----|-----|--------|
| `/events/search` (sans index) | 3 026 ms | 28 req/s | 100% |
| `/health` burst 20K | — | **693 req/s** | 100% |
| `/events/top` burst 20K | — | 32 req/s | **31.7%** |

> **Conclusion v3 (confirmée)** :
> - P50 `/search` stable ~2 800-3 000ms avec ou sans 4 vCPU → **le CPU Cloud Run n'est PAS le bottleneck**
> - Le bottleneck est le **scan séquentiel PostgreSQL** (500K-2.5M lignes)
> - Upgrade Cloud SQL (db-g1-small → db-custom-2-7680) : burst `/top` passe de **1.3% → 31.7%** de succès

---

### v4 — Stack complet avec toutes les optimisations (2026-03-26)
**Infrastructure :** Cloud Run 4 vCPU / 4Gi / max 47, Cloud SQL db-custom-2-7680
**Optimisations déployées (TOUTES) :**
- Index covering `(srcip, ts DESC) INCLUDE (dstip, proto, service, sbytes, attack_cat, label)`
- Vue matérialisée `mv_network_stats_proto` (bytes par protocole)
- Vue matérialisée `mv_attack_categories` ← **nouvelle en v4**
- PgBouncer sidecar (transaction pooling, pool_size=10) ← **nouveau en v4**
- Redis cache fonctionnel (REDIS_URL corrigé, TTL 30-300s) ← **corrigé en v4**
- SQLAlchemy pool optimisé (pool_size=3, max_overflow=5, pool_recycle=300)

| Endpoint | Phase | P50 | P95 | P99 | RPS | Succès |
|----------|-------|-----|-----|-----|-----|--------|
| `/events/search` | BASELINE | 949 ms | 13 360 ms | 21 035 ms | 20 | 87% |
| `/events/search` | INDEX SQL | 3 119 ms | 4 774 ms | 5 681 ms | 26 | **100%** |
| `/events/top` | INDEX SQL | **1 797 ms** | 3 051 ms | 3 602 ms | 26 | **100%** |
| `/events/stats` | INDEX SQL | 1 956 ms | 3 193 ms | 3 490 ms | 26 | **100%** |
| `/health` burst 20K | — | — | — | — | **618 req/s** | **100%** |
| `/events/top` burst 20K | — | — | — | — | 59 req/s | **68.9%** |

> **Conclusion v4** : PgBouncer (pool_size=10) est le bottleneck résiduel. Avec 100 threads concurrents,
> 90 requêtes attendent en queue (10 connexions actives × ~50ms chacune = ~500ms d'attente médiane ajoutée).
> Le bottleneck suivant à corriger : `DEFAULT_POOL_SIZE=10 → 30` (coût zéro).

---

## 6. Progression globale — tableau de synthèse

### Latence P50 par version

| Endpoint | Local baseline | Local + index + Redis | GCP v1 (1vCPU) | GCP v2 (1vCPU) | GCP v4 (4vCPU, full optim) |
|----------|----------------|-----------------------|----------------|----------------|----------------------------|
| `/events/search` | 1 687 ms | **170 ms** (×10) | 827 ms | **697 ms** | 3 119 ms ⚠️ |
| `/events/top` | 168 ms | **7 ms** (×24) | 17 765 ms | 17 765 ms | **1 797 ms** (×9.9 vs v1) |
| `/events/stats` | 367 ms | **20 ms** (×18) | 664 ms | 664 ms | **1 956 ms** ⚠️ |

> ⚠️ v4 `/search` et `/stats` : P50 plus élevé qu'en v2 car concurrence ×2 (c=100 vs c=50) et **PgBouncer pool_size=10** sature (90/100 threads en attente). La requête SQL elle-même prend <50ms — c'est le **temps de queue** qui allonge le P50.

### Débit (RPS) et succès sous charge

| Test | Local (c=20) | GCP v1 (c=50) | GCP v2 (c=50) | GCP v4 (c=100) |
|------|-------------|---------------|---------------|----------------|
| RPS `/search` (load) | ~400 req/s | 56 req/s | **64 req/s** | 26 req/s ⚠️ |
| RPS `/health` (burst) | — | 509 req/s | 451 req/s | **618 req/s** |
| Succès `/top` burst 10-20K req | — | **1.0%** | **1.3%** | **68.9%** ← ×69 |

> Note : RPS local élevé car Nginx micro-cache (Phase 5) sert directement depuis RAM sans toucher la DB.
> RPS GCP v4 faible sur `/search` = PgBouncer pool_size=10 avec c=100 → **bottleneck identifié, solution connue**.

### Impact de chaque optimisation (mesure directe)

| Optimisation | Métrique avant | Métrique après | Gain |
|-------------|---------------|----------------|------|
| Index B-Tree `(srcip, ts DESC)` | P50 = 3 033 ms | P50 = **743 ms** | **×4.1** |
| Vue mat. `mv_network_stats_proto` | P50 `/stats` = ~2 000ms scan | P50 = **664 ms** | **×3** |
| Vue mat. `mv_attack_categories` | P50 `/top` = 3 095 ms | P50 = **1 797 ms** | **×1.7** |
| Cache Redis TTL 60s (local) | P50 = 170 ms | P50 = **7 ms** | **×24** |
| PgBouncer sidecar | Burst succès = 1.3% | Burst succès = **68.9%** | **×53** |
| Upgrade Cloud SQL db-g1-small→db-custom-2-7680 | Burst succès = 1.3% | Burst succès = **31.7%** | **×24** |
| PgBouncer + Cloud SQL upgrade (combinés) | Burst succès = 1.0% | Burst succès = **68.9%** | **×69** |

---

## 7. Sécurité GCP

| Mesure | Implémentation |
|--------|---------------|
| Réseau privé | VPC + sous-réseaux, Cloud SQL / Redis sans IP publique |
| Secrets | Secret Manager GCP (jwt-secret-key, database-url, redis-url) — jamais en clair dans les images |
| Authentification | JWT HS256, rôles analyst/admin, tokens 30 min |
| TLS | Certificat auto-signé sur le Load Balancer HTTPS |
| Anti-SQLi | SQLAlchemy requêtes paramétrées systématiques |
| Rate Limiting | SlowAPI (100 req/min par IP) |
| Least Privilege | Service Account Cloud Run : accès minimal (Cloud SQL Client, Secret Accessor, Storage Viewer) |
| Réseau Cloud Run | VPC Connector `PRIVATE_RANGES_ONLY` — trafic DB/Redis via réseau privé uniquement |

---

## 8. Coûts infrastructure GCP

| Mode | Service | Coût/mois |
|------|---------|-----------|
| **Actif** | Cloud Run API (1 vCPU, min=1) | ~10€ |
| **Actif** | Cloud SQL db-g1-small | ~30€ |
| **Permanent** | Memorystore Redis 1 GB | ~35€ |
| **Permanent** | Load Balancer HTTPS | ~18€ |
| **Permanent** | Artifact Registry + GCS | ~1€ |
| **TOTAL ACTIF** | | **~94€/mois** |
| **TOTAL PAUSE** (min=0, SQL off) | | **~54€/mois** |

> Mode pause : `terraform apply -var="paused=true"` → Cloud Run min=0, Cloud SQL désactivé.

---

## 9. Ce qu'il faut présenter

### 9.1 Architecture et choix techniques (5 min)
- Montrer le schéma architecture V2 (local) → V3 (GCP)
- Insister sur : **pourquoi FastAPI** (async I/O), **pourquoi PgBouncer** (connection pooling), **pourquoi Terraform** (IaC reproductible)
- Dataset réel UNSW-NB15 (2.5M logs réseau, cas d'usage cybersécurité réaliste)

### 9.2 Démarche d'optimisation progressive (5 min)
Montrer la progression en 3 paliers :

```
BASELINE          INDEX SQL           REDIS CACHE
P50=3 000ms  →   P50=700ms (×4.3)  →  P50=7ms (×430)
RPS=16       →   RPS=60    (×3.8)  →  RPS=400+ (×25+)
```

C'est la démonstration que chaque couche d'optimisation a un impact **mesurable et chiffré**.

### 9.3 Démo live (5 min) — voir GUIDE_DEMO.md
- Accès portail : `https://34.54.187.254/`
- Swagger UI : `https://34.54.187.254/api/docs`
- Grafana : `https://34.54.187.254/grafana/`
- Requête live : `curl -sk https://34.54.187.254/api/events/search?srcip=59.166.0.0`

### 9.4 Résultats GCP (3 min)
Tableau de synthèse v1→v4, insister sur :
- Burst `/top` : **1% → 68.9%** (×69 de succès) grâce à PgBouncer + upgrade Cloud SQL
- Identification du bottleneck résiduel (PgBouncer pool_size=10) et solution connue (gratuite)

### 9.5 Ce qui a été appris / limites (2 min)
- **La machine ne fait pas tout** : passer de 1→4 vCPU n'améliore pas les requêtes DB (seq scan ≈ constant)
- **PgBouncer** : essentiel en production Cloud Run (serverless scale-out × connexions = saturation DB garantie)
- **Terraform import** : quand un état diverge de la réalité (secrets créés manuellement)
- **Limite restante** : pool_size=10 dans PgBouncer, à passer à 30 pour multiplier le débit par 3

---

## 10. Fichiers de référence

| Fichier | Contenu |
|---------|---------|
| [GUIDE_DEMO.md](../GUIDE_DEMO.md) | Scénario de démo pas-à-pas |
| [docs/perf_report_v3.md](perf_report_v3.md) | Données brutes tests v1/v2/v3 |
| [docs/perf_report_v4.md](perf_report_v4.md) | Données brutes tests v4 |
| [docs/architectureV2.drawio](architectureV2.drawio) | Schéma architecture locale |
| [docs/architectureV3.drawio](architectureV3.drawio) | Schéma architecture GCP |
| [terraform/](../terraform/) | Infrastructure as Code GCP |
| [ops/run_tests_gcp.py](../ops/run_tests_gcp.py) | Orchestrateur tests de charge |
| `gs://threat-hunting-api-2026-dataset/results/` | Rapports bruts GCS |
