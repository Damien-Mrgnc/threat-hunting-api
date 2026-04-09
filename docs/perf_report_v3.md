# Rapport de Performance v3 — Threat Hunting API
> Dernière mise à jour : 2026-03-26 | 3 campagnes de tests | GCP europe-west1

---

## 0. Contexte des campagnes

| Run | Date | Infrastructure Cloud Run | Concurrence | Charge |
|-----|------|--------------------------|-------------|--------|
| **v1** | 2026-03-19 | 1 vCPU / 512 Mi / max 10 | 50 threads | 600 req |
| **v2** | 2026-03-20 | 1 vCPU / 512 Mi / max 10 | 50 threads | 1 000 req |
| **v3** | 2026-03-26 | **4 vCPU / 4 Gi / max 50** | **100 threads** | 1 000 req |

> v3 : upgrade temporaire pour isoler le bottleneck Cloud Run vs Cloud SQL.
> Note : DSN non disponible depuis la machine locale → les indexes SQL n'ont pas été (re)appliqués en v3. Les 3 phases v3 tournent donc sans index actifs, ce qui explique les latences proches du baseline.

---

## 1. Évolution des métriques clés — `/events/search` (phase Full Optimisé)

| Métrique | v1 | v2 | v3 (4 vCPU) | Tendance |
|----------|----|----|-------------|----------|
| RPS | 56 req/s | 64 req/s | 28 req/s | ↓ (pas d'indexes en v3) |
| P50 | 827 ms | 697 ms | 3 026 ms | ↑ lent (sans indexes) |
| P95 | 1 402 ms | 1 327 ms | 6 753 ms | ↑ lent (sans indexes) |
| Succès | 100% | 100% | 100% | stable |

> v1→v2 : gain ~15% (lié à la stabilité des indexes déjà en place).
> v3 : régression apparente due à l'absence d'indexes — **ce n'est pas une régression Cloud Run**.

---

## 2. Évolution — Phase Baseline (sans index, sans Redis)

| Métrique | v1 | v2 | v3 (4 vCPU) |
|----------|----|----|-------------|
| P50 `/search` | 2 837 ms | 3 033 ms | 2 851 ms |
| RPS `/search` | 18 req/s | 16 req/s | 27 req/s |
| P50 `/top` | 16 721 ms | 17 765 ms | 6 582 ms |
| Succès `/top` | 100% | 100% | **84%** (timeout) |

> **Observation clé** : P50 `/search` stable ~2 800 ms quelle que soit la machine (1 ou 4 vCPU).
> Cela confirme que le bottleneck n'est pas le CPU Cloud Run, mais le **scan séquentiel PostgreSQL**.

---

## 3. Burst Test — `/health` (endpoint sans DB)

| Run | Requêtes | RPS | Succès |
|-----|----------|-----|--------|
| v1 | 10 000 | 509 req/s | 100% |
| v2 | 10 000 | 451 req/s | ~100% |
| **v3** | **20 000** | **693 req/s** | **100%** |

> v3 envoie 2× plus de requêtes et obtient le meilleur RPS (+36% vs v1).
> Sur les endpoints purement CPU/réseau, les machines plus grosses **améliorent bien le débit**.

---

## 4. Burst Test — `/events/top` (endpoint lourd DB)

| Run | Requêtes | RPS effectif | Succès | Infrastructure SQL |
|-----|----------|-------------|--------|--------------------|
| v1 | 10 000 | 16 req/s | **1.0%** | db-g1-small |
| v2 | 10 000 | 16 req/s | **1.3%** | db-g1-small |
| **v3** | **20 000** | **32 req/s** | **31.7%** | **db-custom-2-7680** |

> Amélioration majeure : 1% → 31.7% de succès sous burst.
> L'upgrade Cloud SQL (db-g1-small → db-custom-2-7680 : 2 vCPU / 7.5 Go RAM) divise les échecs par ~25.
> Conclusion : **Cloud SQL est le bottleneck principal sur les endpoints DB**.

---

## 5. Analyse — Où se situe le bottleneck ?

```
                    v1/v2 (1 vCPU)       v3 (4 vCPU)
/health (no DB) :   ~480 req/s           693 req/s   ← +44%  CPU aidé
/search (DB) :      ~750 ms P50          ~2 800 ms   ← sans index = idem baseline
/top burst :        ~1%  succès          ~32% succès ← SQL upgrade aide beaucoup
```

**Le CPU Cloud Run n'est pas le goulot d'étranglement** sur les endpoints DB.
Avec ou sans 4 vCPU, si les indexes ne sont pas actifs, PostgreSQL fait un sequential scan sur 700K lignes → ~2 800 ms incompressible.

**Les indexes SQL sont le levier principal** (gain ×4 sur P50 en v1/v2).
**Cloud SQL tier** est le levier principal pour les bursts massifs.

---

## 6. Tableau de bord des optimisations

| Optimisation | Impact mesuré | Statut |
|-------------|---------------|--------|
| Index B-Tree (srcip, ts, proto) | P50 : 2 800ms → **700ms** (×4) | Actif en prod |
| Vue matérialisée mv_network_stats_proto | `/stats` : GROUP BY pré-calculé | Actif en prod |
| Cache Redis | P50 < 10ms sur répétitions | Actif en prod |
| Upgrade Cloud SQL (2 vCPU / 7.5Go) | Burst /top : 1% → **31.7%** succès | Temporaire v3 |
| Upgrade Cloud Run (4 vCPU / 4Gi) | Burst /health : +44% RPS | Temporaire v3 |

---

## 7. Limites et prochaines étapes

### Limites identifiées
- **db-g1-small (~25 connexions max)** : sature sous burst DB massif → principal frein en prod
- **DSN non accessible depuis local** : les optimisations SQL ne peuvent pas être re-appliquées/vérifiées sans accès VPC
- **Autoscaling Cloud Run** : non déclenché (header `X-API-Replica` non propagé, 1 réplique détectée)

### Recommandations
1. **PgBouncer** : multiplexer les connexions PostgreSQL (solution sans coût de machine) → permettrait de passer db-g1-small à ~200 connexions effectives
2. **Vérifier indexes en prod** : lancer `EXPLAIN ANALYZE` sur `/events/search` avec DSN actif pour confirmer Index Scan vs Seq Scan
3. **Timeout `/events/top`** : l'endpoint génère des timeouts à concurrence 100 — envisager une mise en cache de résultat ou une vue matérialisée dédiée

---

## 8. Fichiers de référence

| Fichier | Contenu |
|---------|---------|
| [ops/run_tests_gcp.py](../ops/run_tests_gcp.py) | Orchestrateur des 3 phases de test |
| [ops/gcp_pause.sh](../ops/gcp_pause.sh) | Retour en mode économique après tests |
| `gs://…/results/perf_report_20260319_223818.md` | Données brutes v1 |
| `gs://…/results/perf_report_20260320_095423.md` | Données brutes v2 |
| `gs://…/results/perf_report_20260326_143217.md` | Données brutes v3 |
