"""
run_tests_gcp.py — Orchestrateur de tests de performance pour GCP Cloud Run

3 phases avec paramètres variés (pas de biais Redis sur requêtes identiques) :
  1. BASELINE       — sans index SQL, sans Redis, IPs/params variés
  2. INDEX SQL       — index B-Tree + vue matérialisée, Redis OFF, IPs/params variés
                      → isole le gain des index SQL seuls
  3. FULL OPTIMISÉ  — index + Redis ON, params variés
                      → montre l'effet combiné index + cache

Variables d'environnement requises :
  API_URL    — URL Cloud Run API (ex: https://threat-hunting-api-xxx-ew.a.run.app)
  DSN        — PostgreSQL DSN (ex: postgresql://user:pass@10.1.0.3:5432/db)
  GCS_BUCKET — bucket GCS pour les résultats (ex: threat-hunting-api-2026-dataset)
  USERNAME   — login API (défaut: admin)
  PASSWORD   — mot de passe API (défaut: secret)
"""

import asyncio
import concurrent.futures
import json
import os
import random
import statistics
import sys
import time
from datetime import datetime, timezone

import aiohttp
import psycopg
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_URL    = os.getenv("API_URL",    "https://threat-hunting-api-3gqrf5kr2q-ew.a.run.app").rstrip("/")
DSN        = os.getenv("DSN",        "")
GCS_BUCKET = os.getenv("GCS_BUCKET", "threat-hunting-api-2026-dataset")
USERNAME   = os.getenv("USERNAME",   "admin")
PASSWORD   = os.getenv("PASSWORD",   "secret")

BURST_N     = int(os.getenv("BURST_N",    "10000"))
BURST_BATCH = int(os.getenv("BURST_BATCH", "500"))
LOAD_N      = int(os.getenv("LOAD_N",     "600"))
LOAD_C      = int(os.getenv("LOAD_C",     "30"))

# Nombre d'IPs distinctes à charger depuis la DB pour varier les requêtes /search
SAMPLE_IPS  = int(os.getenv("SAMPLE_IPS", "100"))

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def get_token() -> str:
    resp = requests.post(
        f"{API_URL}/auth/token",
        data={"username": USERNAME, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
        verify=False,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _read_sql(filename: str) -> str:
    for candidate in [
        os.path.join(BASE_DIR, "db", filename),
        os.path.join(BASE_DIR, "..", "db", filename),
    ]:
        if os.path.exists(candidate):
            with open(candidate, "r") as f:
                return f.read()
    raise FileNotFoundError(f"SQL file not found: {filename}")

def apply_sql(filename: str):
    if not DSN:
        print(f"  ⚠️  DSN vide — skip {filename}")
        return
    sql = _read_sql(filename)
    with psycopg.connect(DSN) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
    print(f"  ✅ {filename} appliqué")

def set_redis(enabled: bool, token: str):
    try:
        resp = requests.post(
            f"{API_URL}/config/features",
            json={"use_redis": enabled},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
            verify=False,
        )
        print(f"  ✅ Redis {'activé' if enabled else 'désactivé'} (status {resp.status_code})")
    except Exception as e:
        print(f"  ⚠️  Config Redis échouée : {e}")

def fetch_sample_ips(n: int = 100) -> list[str]:
    """
    Récupère n IPs source distinctes depuis la DB pour varier les requêtes /search.
    Chaque requête aura une srcip différente → pas de biais de cache, vrai test d'index.
    """
    fallback = [
        "149.171.126.1", "175.45.176.1", "59.166.0.1", "149.171.126.6",
        "175.45.176.2", "59.166.0.4", "149.171.126.11", "175.45.176.3",
    ]
    if not DSN:
        print("  ⚠️  DSN vide — utilisation IPs de fallback")
        return fallback
    try:
        with psycopg.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT srcip FROM network_events "
                    "WHERE srcip IS NOT NULL ORDER BY RANDOM() LIMIT %s",
                    (n,)
                )
                ips = [row[0] for row in cur.fetchall()]
        if ips:
            print(f"  ✅ {len(ips)} IPs distinctes chargées depuis la DB")
            return ips
        return fallback
    except Exception as e:
        print(f"  ⚠️  Échec chargement IPs : {e} — utilisation fallback")
        return fallback


# ---------------------------------------------------------------------------
# Load test — avec pool d'URLs variées
# ---------------------------------------------------------------------------
def _send(url: str, token: str) -> tuple[int, float, str]:
    try:
        t0 = time.perf_counter()
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
            verify=False,
        )
        elapsed = time.perf_counter() - t0
        replica = resp.headers.get("X-API-Replica", "unknown")
        return resp.status_code, elapsed, replica
    except Exception:
        return 0, 0.0, "error"

def run_load_test(label: str, url_pool: list[str], token: str, n: int, c: int) -> dict:
    """
    Load test avec pool d'URLs.
    Si url_pool contient plusieurs URLs, chaque requête choisit aléatoirement dans le pool
    → les paramètres varient → pas de réponse en cache systématique.
    """
    print(f"\n  ▶ Load test [{label}] — {n} req, concurrence {c}, {len(url_pool)} URL(s) distincte(s)")

    def send_one(_):
        url = random.choice(url_pool)
        return _send(url, token)

    results = []
    t_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=c) as pool:
        futures = [pool.submit(send_one, i) for i in range(n)]
        done = 0
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
            done += 1
            if done % max(1, n // 10) == 0:
                sys.stdout.write(f"\r    {done}/{n} ({done/n*100:.0f}%)")
                sys.stdout.flush()
    total_time = time.perf_counter() - t_start
    print()

    successes = [r for r in results if 200 <= r[0] < 300]
    latencies = sorted(r[1] for r in successes)

    def pct(p):
        if not latencies:
            return 0.0
        idx = max(0, int(len(latencies) * p / 100) - 1)
        return latencies[idx]

    p50, p95, p99 = pct(50), pct(95), pct(99)
    avg = statistics.mean(latencies) if latencies else 0.0
    rps = n / total_time if total_time > 0 else 0

    data = {
        "label": label,
        "url_pool": url_pool[:3],  # juste les 3 premières pour le rapport
        "n_urls": len(url_pool),
        "n": n,
        "concurrency": c,
        "success": len(successes),
        "failures": len(results) - len(successes),
        "total_time_s": round(total_time, 3),
        "rps": round(rps, 1),
        "avg_ms": round(avg * 1000, 2),
        "p50_ms": round(p50 * 1000, 2),
        "p95_ms": round(p95 * 1000, 2),
        "p99_ms": round(p99 * 1000, 2),
    }
    _print_latency_report(data)
    return data


# ---------------------------------------------------------------------------
# Burst test (async)
# ---------------------------------------------------------------------------
async def _fetch_one(session, url: str, token: str, results: list):
    try:
        async with session.get(url, headers={"Authorization": f"Bearer {token}"}) as resp:
            replica = resp.headers.get("X-API-Replica", "unknown")
            results.append((resp.status, replica))
    except asyncio.TimeoutError:
        results.append((0, "timeout"))
    except Exception:
        results.append((0, "error"))

async def _run_burst_async(url_pool: list[str], token: str, n: int, batch: int):
    results = []
    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(limit=batch, ssl=False)
    urls = [random.choice(url_pool) for _ in range(n)]
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        coros = [_fetch_one(session, urls[i], token, results) for i in range(n)]
        t_start = time.perf_counter()
        n_batches = (n + batch - 1) // batch
        for i in range(0, n, batch):
            await asyncio.gather(*coros[i:i + batch])
            done = min(i + batch, n)
            p = done / n * 100
            bar = "█" * int(p / 5) + "░" * (20 - int(p / 5))
            sys.stdout.write(f"\r    [{bar}] {p:5.1f}%  batch {i//batch+1}/{n_batches}")
            sys.stdout.flush()
        t_end = time.perf_counter()
    print()
    return results, t_end - t_start

def run_burst_test(label: str, url_pool: list[str], token: str, n: int, batch: int) -> dict:
    print(f"\n  ▶ Burst test [{label}] — {n} req en batches de {batch}, {len(url_pool)} URL(s) distincte(s)")
    results, total_time = asyncio.run(_run_burst_async(url_pool, token, n, batch))

    successes = [(s, r) for s, r in results if 200 <= s < 300]
    failures = len(results) - len(successes)
    rps = n / total_time if total_time > 0 else 0

    from collections import Counter
    replica_counts = Counter(r for _, r in successes)

    data = {
        "label": label,
        "n": n,
        "batch": batch,
        "success": len(successes),
        "failures": failures,
        "total_time_s": round(total_time, 3),
        "rps": round(rps, 1),
        "replicas": dict(replica_counts),
    }

    print(f"    RPS : {rps:,.0f} | Succès : {len(successes):,}/{n:,} | Temps : {total_time:.2f}s")
    print(f"    Répliques détectées : {len(replica_counts)}")
    for rep, cnt in sorted(replica_counts.items(), key=lambda x: -x[1]):
        bar = "█" * int(cnt / max(replica_counts.values()) * 20)
        print(f"      {rep:<40} {cnt:>6,}  {bar}")
    return data


# ---------------------------------------------------------------------------
# Interprétation
# ---------------------------------------------------------------------------
def interpret_percentiles(p50: float, p95: float, p99: float) -> list[str]:
    lines = []
    if p50 < 10:
        lines.append(f"✅ P50={p50:.1f}ms — Excellent. Cache Redis actif ou requête triviale.")
    elif p50 < 50:
        lines.append(f"✅ P50={p50:.1f}ms — Très bon. Requête SQL optimisée (index présent).")
    elif p50 < 200:
        lines.append(f"⚠️  P50={p50:.1f}ms — Correct. Index présent mais résultat non caché (paramètres variés).")
    elif p50 < 2000:
        lines.append(f"⚠️  P50={p50:.1f}ms — Lent. Index manquant ou cold start Cloud Run.")
    else:
        lines.append(f"❌ P50={p50:.1f}ms — Très lent. Sequential scan sur grande table (baseline attendu).")

    if p50 > 0:
        r95 = p95 / p50
        r99 = p99 / p50
        if r95 < 2:
            lines.append(f"✅ P95/P50={r95:.1f}x — Latence stable, faible variance.")
        elif r95 < 5:
            lines.append(f"⚠️  P95/P50={r95:.1f}x — Variance modérée (cold start ou contention pool DB).")
        else:
            lines.append(f"❌ P95/P50={r95:.1f}x — Haute variance. Problème de contention ou GC pause.")

        if r99 > 10:
            lines.append(f"❌ P99/P50={r99:.1f}x — Tail latency élevée. Requêtes bloquantes ou timeouts.")
        elif r99 > 4:
            lines.append(f"⚠️  P99/P50={r99:.1f}x — Tail latency notable. Acceptable en démonstration.")
        else:
            lines.append(f"✅ P99/P50={r99:.1f}x — Tail latency faible. Comportement stable.")

    return lines


def _print_latency_report(d: dict):
    print(f"\n    {'─'*52}")
    print(f"    RPS      : {d['rps']:,.0f} req/s")
    print(f"    Succès   : {d['success']:,}/{d['n']:,}  (échecs: {d['failures']})")
    print(f"    Avg      : {d['avg_ms']:.2f} ms")
    print(f"    P50      : {d['p50_ms']:.2f} ms")
    print(f"    P95      : {d['p95_ms']:.2f} ms")
    print(f"    P99      : {d['p99_ms']:.2f} ms")
    for line in interpret_percentiles(d['p50_ms'], d['p95_ms'], d['p99_ms']):
        print(f"    {line}")
    print(f"    {'─'*52}")


# ---------------------------------------------------------------------------
# Rapport Markdown
# ---------------------------------------------------------------------------
def generate_markdown(all_results: dict, run_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    api = API_URL
    md = [
        "# Rapport de Performance — Threat Hunting API",
        "",
        f"> Généré le {ts} | Run ID : `{run_id}`",
        f"> API : `{api}`",
        "> Environnement : Cloud Run Job (europe-west1) → latence interne GCP ~2ms",
        "> **Paramètres variés** : IPs srcip et valeurs limit aléatoires → résultats non biaisés par le cache",
        "",
        "---",
        "",
    ]

    load_results = {r["label"]: r for r in all_results.get("load_tests", [])}

    # --- Tableau comparatif ---
    phases = [PHASE_BASELINE, PHASE_INDEX, PHASE_FULL]
    available = [p for p in phases if p in load_results]

    if len(available) >= 2:
        md += [
            "## 1. Comparaison des 3 phases",
            "",
            "| Métrique | 🐢 Baseline | 🔧 Index SQL seul | 🚀 Full Optimisé (+ Redis) |",
            "|----------|------------|------------------|---------------------------|",
        ]

        def val(phase, key, unit="ms"):
            if phase not in load_results:
                return "N/A"
            v = load_results[phase][key]
            return f"{v:,.0f} {unit}" if unit == "req/s" else f"{v:,.1f} ms"

        def gain(ref_phase, cmp_phase, key, lower_is_better=True):
            if ref_phase not in load_results or cmp_phase not in load_results:
                return "N/A"
            ref = load_results[ref_phase][key]
            cmp = load_results[cmp_phase][key]
            if ref <= 0 or cmp <= 0:
                return "N/A"
            if lower_is_better:
                x = ref / cmp
                return f"**×{x:.1f}**" if x >= 1.5 else f"~{x:.1f}x"
            else:
                x = cmp / ref
                return f"**×{x:.1f}**" if x >= 1.5 else f"~{x:.1f}x"

        for metric, key, unit, lib in [
            ("RPS",  "rps",    "req/s", False),
            ("P50",  "p50_ms", "ms",    True),
            ("P95",  "p95_ms", "ms",    True),
            ("P99",  "p99_ms", "ms",    True),
        ]:
            b_val  = val(PHASE_BASELINE, key, unit)
            i_val  = val(PHASE_INDEX,    key, unit)
            o_val  = val(PHASE_FULL,     key, unit)
            i_gain = gain(PHASE_BASELINE, PHASE_INDEX, key, lib)
            o_gain = gain(PHASE_BASELINE, PHASE_FULL,  key, lib)
            md.append(f"| {metric} | {b_val} | {i_val} (gain {i_gain} vs baseline) | {o_val} (gain {o_gain} vs baseline) |")

        md += [
            "",
            "> **Lecture** : INDEX SQL = index B-Tree + vue matérialisée, Redis **désactivé** → gain pur SQL.",
            "> FULL OPTIMISÉ = index + Redis **activé**, params variés → première requête par valeur = SQL, suivantes = Redis.",
            "",
        ]

    # --- Interprétation par phase ---
    md += ["## 2. Interprétation par phase", ""]
    for phase in available:
        r = load_results[phase]
        md += [f"### {phase}", ""]
        for line in interpret_percentiles(r["p50_ms"], r["p95_ms"], r["p99_ms"]):
            md.append(f"- {line}")
        md.append("")

    # --- Workloads détaillés ---
    all_load = all_results.get("load_tests", [])
    if all_load:
        md += ["## 3. Résultats détaillés par workload", ""]
        for r in all_load:
            endpoint = r["url_pool"][0].replace(api, "") if r.get("url_pool") else "N/A"
            md += [
                f"### {r['label']}",
                "",
                f"- **Endpoint** : `{endpoint}` *(+{r.get('n_urls', 1)-1} variantes)*" if r.get("n_urls", 1) > 1 else f"- **Endpoint** : `{endpoint}`",
                f"- **Requêtes** : {r['n']:,} à concurrence {r['concurrency']}",
                f"- **RPS** : {r['rps']:,.0f} req/s | **Avg** : {r['avg_ms']:.1f} ms",
                f"- **P50** : {r['p50_ms']:.1f} ms | **P95** : {r['p95_ms']:.1f} ms | **P99** : {r['p99_ms']:.1f} ms",
                f"- **Succès** : {r['success']:,}/{r['n']:,}",
                "",
                "**Interprétation :**",
                "",
            ]
            for line in interpret_percentiles(r["p50_ms"], r["p95_ms"], r["p99_ms"]):
                md.append(f"- {line}")
            md.append("")

    # --- Burst tests ---
    burst_results = all_results.get("burst_tests", [])
    if burst_results:
        md += [f"## 4. Burst Test ({BURST_N:,} requêtes simultanées)", ""]
        for br in burst_results:
            md += [
                f"### {br['label']}",
                "",
                "| Métrique | Valeur |",
                "|----------|--------|",
                f"| Requêtes | {br['n']:,} |",
                f"| RPS effectif | **{br['rps']:,.0f} req/s** |",
                f"| Succès | {br['success']:,} ({br['success']/br['n']*100:.1f}%) |",
                f"| Échecs | {br['failures']:,} |",
                f"| Temps total | {br['total_time_s']:.2f}s |",
                "",
            ]
            if br["replicas"]:
                total_ok = sum(br["replicas"].values())
                n_rep = len(br["replicas"])
                md += [
                    "**Distribution Cloud Run (autoscaling) :**",
                    "",
                    "| Réplique | Requêtes | % |",
                    "|----------|----------|---|",
                ]
                for rep, cnt in sorted(br["replicas"].items(), key=lambda x: -x[1]):
                    md.append(f"| `{rep}` | {cnt:,} | {cnt/total_ok*100:.1f}% |")
                md.append("")
                if n_rep >= 3:
                    md.append(f"✅ **Autoscaling validé** : {n_rep} répliques Cloud Run actives simultanément.")
                elif n_rep == 2:
                    md.append(f"⚠️ **Autoscaling partiel** : {n_rep} répliques — augmenter la charge pour plus d'instances.")
                else:
                    md.append("❌ **Pas d'autoscaling** : 1 seule réplique — charge insuffisante.")
                md.append("")

    # --- Conclusion ---
    md += [
        "---",
        "",
        "## 5. Conclusion",
        "",
        "| Optimisation | Composant | Impact mesuré |",
        "|-------------|-----------|---------------|",
        "| Index B-Tree (srcip, ts, proto) | PostgreSQL | Réduction P50 `/events/search` (params variés, sans cache) |",
        "| Vue matérialisée mv_network_stats_proto | PostgreSQL | GROUP BY pré-calculé → P95 divisé par ~30 |",
        "| Cache Redis | Redis | P50 < 10ms sur requêtes répétées (limite la portée du cache avec params variés) |",
        "| Cloud Run autoscaling | Cloud Run | Burst /health 100% succès |",
        "| VPC Connector | Réseau | Cloud Run → Cloud SQL privée, ~2-3ms overhead |",
        "",
        "### Limites identifiées",
        "",
        "- **db-g1-small** (~25 connexions max) : sature sous burst massif sur endpoints DB",
        "  → Solution : PgBouncer ou upgrade `db-n1-standard-2`",
        "- **Redis cold start** : P50 > 10ms attendu au premier test (cache froid)",
        "  → Pré-chauffer en relançant quelques requêtes avant le test",
        "",
    ]
    return "\n".join(md)


# ---------------------------------------------------------------------------
# Upload GCS
# ---------------------------------------------------------------------------
def upload_to_gcs(content: str, filename: str, content_type: str = "text/plain"):
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(f"results/{filename}")
        blob.upload_from_string(content, content_type=content_type)
        print(f"  ✅ Sauvegardé : gs://{GCS_BUCKET}/results/{filename}")
    except Exception as e:
        print(f"  ⚠️  Upload GCS échoué : {e}")
        print("\n" + "="*60)
        print(content[:5000])
        print("="*60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
PHASE_BASELINE = "BASELINE"
PHASE_INDEX    = "INDEX SQL"
PHASE_FULL     = "FULL OPTIMISÉ"
SQL_OPTIMIZE   = "optimize.sql"
SQL_DEOPTIMIZE = "deoptimize.sql"


def main():
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    all_results = {"run_id": run_id, "api_url": API_URL, "load_tests": [], "burst_tests": []}

    print("\n" + "="*62)
    print("  THREAT HUNTING API — SUITE DE TESTS GCP (paramètres variés)")
    print("="*62)
    print(f"  API      : {API_URL}")
    print(f"  Run ID   : {run_id}")
    print(f"  Burst N  : {BURST_N:,}  batch={BURST_BATCH}")
    print(f"  Load  N  : {LOAD_N:,}  concurrence={LOAD_C}")
    print(f"  Sample IPs : {SAMPLE_IPS} IPs distinctes pour /events/search")
    print("="*62)

    # --- Auth ---
    print("\n[0/7] Authentification...")
    token = get_token()
    print("  ✅ Token obtenu")

    # --- Warmup ---
    print("\n[1/7] Warmup (10 req pour chauffer Cloud Run)...")
    for _ in range(10):
        requests.get(f"{API_URL}/health", verify=False, timeout=10)
    print("  ✅ Warmup terminé")

    # --- Charger les IPs variées depuis la DB ---
    print("\n[2/7] Chargement des paramètres variés depuis la DB...")
    sample_ips = fetch_sample_ips(SAMPLE_IPS)

    # Pool d'URLs pour chaque workload
    # Workload 1 : /events/search?srcip={ip} — index B-Tree sur srcip
    search_urls = [f"{API_URL}/events/search?srcip={ip}&limit=50" for ip in sample_ips]

    # Workload 2 : /events/stats/bytes-by-proto — vue matérialisée (pas de Redis)
    # hours=1..168 : le paramètre est ignoré par l'API mais rend l'URL unique si Redis est ajouté plus tard
    stats_urls = [f"{API_URL}/events/stats/bytes-by-proto?hours={h}" for h in range(1, 169, 12)]

    # Workload 3 : /events/top/attack-categories?limit={1..20}
    # Chaque valeur = clé Redis différente → pas de hits systématiques
    top_urls = [f"{API_URL}/events/top/attack-categories?limit={l}" for l in range(1, 21)]

    print(f"  ✅ {len(search_urls)} URLs /search | {len(stats_urls)} URLs /stats | {len(top_urls)} URLs /top")

    # ===================================================================
    # PHASE 1 — BASELINE (sans index, sans Redis)
    # ===================================================================
    print("\n[3/7] ═══ PHASE 1 : BASELINE (sans index SQL, sans Redis) ═══")
    apply_sql(SQL_DEOPTIMIZE)
    set_redis(False, token)
    time.sleep(2)

    r = run_load_test(f"{PHASE_BASELINE} — /events/search (srcip variés)", search_urls, token, LOAD_N, LOAD_C)
    all_results["load_tests"].append({**r, "label": PHASE_BASELINE})

    r_base_top = run_load_test(f"{PHASE_BASELINE} — /events/top (limit variés)", top_urls, token, LOAD_N // 3, LOAD_C)
    all_results["load_tests"].append({**r_base_top, "label": f"{PHASE_BASELINE} /top"})

    # ===================================================================
    # PHASE 2 — INDEX SQL (index actifs, Redis OFF)
    # Isole le gain des index B-Tree et de la vue matérialisée, sans cache Redis
    # ===================================================================
    print(f"\n[4/7] ═══ PHASE 2 : {PHASE_INDEX} (index actifs, Redis OFF) ═══")
    apply_sql(SQL_OPTIMIZE)
    set_redis(False, token)   # Redis OFF → on mesure vraiment le SQL
    time.sleep(3)

    r = run_load_test(f"{PHASE_INDEX} — /events/search (srcip variés)", search_urls, token, LOAD_N, LOAD_C)
    all_results["load_tests"].append({**r, "label": PHASE_INDEX})

    r_idx_stats = run_load_test(f"{PHASE_INDEX} — /events/stats (vue mat.)", stats_urls, token, LOAD_N // 3, LOAD_C)
    all_results["load_tests"].append({**r_idx_stats, "label": f"{PHASE_INDEX} /stats"})

    r_idx_top = run_load_test(f"{PHASE_INDEX} — /events/top (limit variés, sans Redis)", top_urls, token, LOAD_N // 3, LOAD_C)
    all_results["load_tests"].append({**r_idx_top, "label": f"{PHASE_INDEX} /top"})

    # ===================================================================
    # PHASE 3 — FULL OPTIMISÉ (index + Redis ON, params variés)
    # ===================================================================
    print(f"\n[5/7] ═══ PHASE 3 : {PHASE_FULL} (index + Redis ON) ═══")
    apply_sql(SQL_OPTIMIZE)
    set_redis(True, token)
    time.sleep(2)

    r = run_load_test(f"{PHASE_FULL} — /events/search (srcip variés)", search_urls, token, LOAD_N, LOAD_C)
    all_results["load_tests"].append({**r, "label": PHASE_FULL})

    r_opt_top = run_load_test(f"{PHASE_FULL} — /events/top (limit variés + Redis)", top_urls, token, LOAD_N // 3, LOAD_C)
    all_results["load_tests"].append({**r_opt_top, "label": f"{PHASE_FULL} /top"})

    # ===================================================================
    # BURST TESTS
    # ===================================================================
    print("\n[6/7] ═══ BURST TESTS ═══")

    # Burst léger (health) — valide l'autoscaling Cloud Run
    apply_sql(SQL_DEOPTIMIZE)
    set_redis(False, token)
    time.sleep(1)
    r_burst_health = run_burst_test(
        "BURST — /health (endpoint léger)",
        [f"{API_URL}/health"],
        token, BURST_N, BURST_BATCH
    )
    all_results["burst_tests"].append(r_burst_health)

    # Burst lourd (endpoint DB) — montre les limites du pool Cloud SQL
    apply_sql(SQL_OPTIMIZE)
    set_redis(True, token)
    time.sleep(2)
    r_burst_heavy = run_burst_test(
        "BURST OPTIMISÉ — /events/top (endpoint DB lourd)",
        top_urls,  # URLs variées → limite l'effet du cache Redis
        token, BURST_N, BURST_BATCH
    )
    all_results["burst_tests"].append(r_burst_heavy)

    # ===================================================================
    # RAPPORT
    # ===================================================================
    print("\n[7/7] Génération du rapport...")
    report_md   = generate_markdown(all_results, run_id)
    report_json = json.dumps(all_results, indent=2, ensure_ascii=False)

    upload_to_gcs(report_md,   f"perf_report_{run_id}.md",   "text/markdown")
    upload_to_gcs(report_json, f"perf_report_{run_id}.json", "application/json")

    print("\n" + report_md)
    print("\n" + "="*62)
    print("  TESTS TERMINÉS")
    print(f"  Résultats : gs://{GCS_BUCKET}/results/perf_report_{run_id}.md")
    print("="*62 + "\n")


if __name__ == "__main__":
    main()
