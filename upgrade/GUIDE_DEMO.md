# Guide de Démo — Threat Hunting API sur GCP

> **Durée estimée** : 10-15 minutes
> **Prérequis** : navigateur ouvert, onglets pré-chargés, connexion internet

---

## Avant la démo — Préparer les onglets

Ouvrir ces 5 onglets **à l'avance** (le cold start Cloud Run peut prendre 5-10s) :

| # | URL | Pour montrer |
|---|-----|-------------|
| 1 | `https://34.54.187.254/` | Portail principal |
| 2 | `https://34.54.187.254/interface/` | Threat Interface (login: admin / secret) |
| 3 | `https://34.54.187.254/api/docs` | Swagger UI |
| 4 | `https://34.54.187.254/grafana/` | Grafana (login: admin / admin) |
| 5 | `https://34.54.187.254/prometheus/` | Prometheus |

> ⚠️ Certificat auto-signé — cliquer "Avancé → Continuer" sur chaque onglet

---

## Structure de la démo

```
1. Architecture (2 min)  →  expliquer sans naviguer
2. Portail (1 min)       →  onglet 1
3. API Swagger (2 min)   →  onglet 3
4. Threat Interface (2 min) → onglet 2
5. Observabilité (2 min) →  onglets 4 et 5
6. Performance (3 min)   →  chiffres clés à citer
7. Questions             →  doc de référence
```

---

## 1. Architecture — Présenter sans naviguer (2 min)

**Ce qu'on a déployé sur GCP :**

```
Internet (HTTPS)
       │
       ▼
Cloud Load Balancer (IP fixe : 34.54.187.254)
       │
       ├── /          → Portal Cloud Run    (SPA + docs)
       ├── /api/*     → API Cloud Run       (FastAPI — autoscale 1-10 instances)
       ├── /interface/* → Portal Cloud Run  (SPA Threat Interface)
       ├── /grafana/* → Grafana Cloud Run
       └── /prometheus/* → Prometheus Cloud Run
               │
               ├── Cloud SQL PostgreSQL 15  (réseau privé VPC — 10.1.0.3)
               ├── Memorystore Redis 6      (réseau privé VPC — 10.4.0.3)
               └── VPC Connector           (pont Cloud Run ↔ ressources privées)
```

**Points à mentionner :**
- Tout est déployé via **Terraform** (13 ressources IaC)
- Cloud Run et Cloud SQL communiquent sur un **réseau privé VPC** (pas d'exposition internet)
- Les secrets (DB URL, JWT, Redis) sont dans **Secret Manager**, jamais dans le code
- Dataset : **UNSW-NB15** (~700 000 événements réseau réels, stocké sur GCS)

---

## 2. Portail principal — Onglet 1 (1 min)

URL : `https://34.54.187.254/`

**À montrer :**
- Page d'accueil avec les 4 services disponibles
- Cliquer sur **Documentation** → montre que les docs sont servies depuis le portail
- Revenir à l'accueil

**À dire :**
> "Le portail est un point d'entrée unique. Tout passe par le Load Balancer — les utilisateurs n'ont qu'une seule URL à retenir."

---

## 3. API Swagger — Onglet 3 (2 min)

URL : `https://34.54.187.254/api/docs`

**À montrer :**

1. **GET /health** → Exécuter → réponse instantanée (status: ok)
   > "Le health check permet à Cloud Run de vérifier que l'instance est prête."

2. **POST /auth/token** → Body : `username=admin&password=secret` → Exécuter → copier le token
   > "Authentification JWT — chaque endpoint protégé nécessite ce token."

3. **Cliquer Authorize** en haut → coller le token

4. **GET /events/search** → `srcip` = une IP au choix (ex: `175.45.176.1`), `limit=10` → Exécuter
   > "Cet endpoint bénéficie d'un index B-Tree sur srcip — gain ×4.1 vs baseline."

5. **(optionnel) GET /events/top/attack-categories** → Exécuter
   > "Cet endpoint fait un full scan — c'est le cas non optimisé qu'on a documenté."

---

## 4. Threat Interface — Onglet 2 (2 min)

URL : `https://34.54.187.254/interface/`

**Connexion :** admin / secret

**À montrer :**
- Dashboard principal avec les statistiques en temps réel
- Tableau des événements réseau (filtres par IP, protocole)
- Graphiques d'attaques par catégorie

**À dire :**
> "L'interface consomme directement l'API FastAPI. Elle est packagée dans l'image Docker du portail et servie comme SPA statique."

---

## 5. Observabilité — Onglets 4 et 5 (2 min)

### Grafana — Onglet 4
URL : `https://34.54.187.254/grafana/` | admin / admin

- Ouvrir le dashboard **Threat Hunting API**
- Montrer : RPS, latence P50/P95, taux d'erreur

> "Grafana scrape Prometheus qui lui-même scrape l'endpoint `/metrics` de l'API FastAPI (format OpenMetrics)."

### Prometheus — Onglet 5
URL : `https://34.54.187.254/prometheus/`

- Taper dans le champ : `http_requests_total`  → Exécuter
- Montrer le graph ou la table

> "Prometheus est déployé sur Cloud Run et configuré pour scraper l'API via HTTPS."

---

## 6. Performance — Chiffres à citer (3 min)

> Ouvrir `upgrade/RAPPORT_PERFORMANCE.md` en local comme support, ou citer de mémoire.

### Les 3 phases testées (endpoint `/events/search`)

| Phase | RPS | P50 | P95 |
|-------|-----|-----|-----|
| 🐢 BASELINE (sans index) | 16 req/s | 3 033 ms | 3 896 ms |
| 🔧 INDEX SQL seul | 60 req/s | 743 ms | 1 416 ms |
| 🚀 FULL OPTIMISÉ (+Redis) | 64 req/s | 697 ms | 1 327 ms |

**À dire :**
> "Sans index, PostgreSQL fait un sequential scan sur 700 000 lignes — P50 à 3 secondes.
> L'index B-Tree sur srcip réduit le P50 à 743ms, soit **×4.1 de gain**.
> Redis ajoute 6% de RPS supplémentaire — faible ici car on teste avec 100 IPs différentes, donc peu de hits cache."

### Burst test — 10 000 requêtes simultanées

| Endpoint | RPS | Succès |
|----------|-----|--------|
| `/health` (léger) | 451 req/s | **99.99%** ✅ |
| `/events/top` (DB lourd) | 16 req/s | **1.3%** ⚠️ |

**À dire :**
> "Le burst sur `/health` valide l'autoscaling Cloud Run — 99.99% de succès sur 10 000 requêtes.
> Le burst sur l'endpoint DB lourd sature le pool Cloud SQL (db-g1-small = 25 connexions max) — comportement documenté, solution identifiée : PgBouncer."

### Optimisations implémentées

| Optimisation | Impact |
|-------------|--------|
| Index B-Tree `(srcip, ts, proto)` | P50 : 3033 → 743 ms (×4.1) |
| Vue matérialisée `mv_network_stats_proto` | 63 req/s sur agrégation globale |
| Cache Redis | +6% RPS sur requêtes répétées |
| Cloud Run autoscaling | 451 req/s, 99.99% succès sur burst |

---

## 7. Questions fréquentes — Réponses prêtes

**"Pourquoi Cloud Run et pas Kubernetes ?"**
> "Cloud Run est serverless — scale to zero, pas de gestion de nodes, facturation à la requête. Pour un workload avec des pics, c'est plus économique (~94€/mois vs ~200€+ sur GKE)."

**"Pourquoi pas de HTTPS avec un vrai certificat ?"**
> "Le Load Balancer supporte les certificats gérés par GCP (Let's Encrypt auto-renew). On utilise un certificat auto-signé ici pour éviter d'avoir un domaine DNS — en prod ce serait un vrai cert."

**"Comment les tests de performance sont exécutés ?"**
> "Depuis un Cloud Run Job (`threat-hunting-tests`) qui tourne dans le même VPC que l'API — latence réseau interne ~2ms. Le job applique/retire les index via psycopg direct et mesure P50/P95/P99 sur 600 requêtes par phase."

**"Qu'est-ce que le dataset UNSW-NB15 ?"**
> "Un dataset académique de trafic réseau réel contenant ~700 000 événements avec labels d'attaques (DoS, Exploits, Reconnaissance...). Il est stocké sur GCS et chargé dans PostgreSQL via un Cloud Run Job de seed."

**"Pourquoi Redis a peu d'impact dans les tests ?"**
> "On a délibérément testé avec 100 IPs distinctes pour éviter le biais de cache — chaque IP génère une clé Redis différente, donc peu de répétitions. En production avec des requêtes répétées, le gain serait beaucoup plus visible (P50 < 10ms vs 700ms)."

---

## Backup — Si quelque chose ne marche pas

| Problème | Solution |
|---------|---------|
| Cold start lent (5-10s) | Attendre — Cloud Run scale de zéro |
| Certificat bloqué | "Avancé → Continuer quand même" |
| Interface ne charge pas | Passer directement à l'onglet Swagger |
| Grafana vide | Montrer Prometheus à la place |
| Auth échoue | Vérifier : login=`admin`, password=`secret` (pas `admin123`) |

---

## Ordre alternatif (démo courte — 5 min)

1. Architecture en 30s (schéma ASCII ci-dessus)
2. **Swagger** → `/health` + auth + `/events/search`
3. **Grafana** → dashboard métriques
4. **Chiffres perf** → citer le tableau des 3 phases

---

*Guide généré le 2026-03-22 | Projet `threat-hunting-api-2026` | europe-west1*
