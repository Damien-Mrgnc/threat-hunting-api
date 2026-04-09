"""
burst_test.py — Test de charge "burst" : 10 000 requêtes simultanées

Différence avec load_test.py :
  - load_test.py : mesure la latence MOYENNE par requête (P50, P95, P99)
  - burst_test.py : mesure le TEMPS TOTAL pour que l'app réponde à N requêtes en même temps

Usage :
  pip install aiohttp
  python ops/burst_test.py --url http://localhost/health -n 10000
  python ops/burst_test.py --url http://localhost/api/v1/events/top/attack-categories -n 5000 --batch 500
"""

import asyncio
import sys
import time
import argparse
from collections import Counter

try:
    import aiohttp
except ImportError:
    print("ERROR: aiohttp n'est pas installé. Lancez : pip install aiohttp")
    sys.exit(1)

DEFAULT_URL = "http://localhost/health"
DEFAULT_N = 10000
DEFAULT_BATCH = 1000
REQUEST_TIMEOUT = 30


async def fetch_one(session: "aiohttp.ClientSession", url: str, results: list) -> None:
    """Envoie une requête GET et enregistre (status, replica) dans la liste partagée."""
    try:
        async with session.get(url) as resp:
            replica = resp.headers.get("X-API-Replica", "unknown")
            results.append((resp.status, replica))
    except asyncio.TimeoutError:
        results.append((0, "timeout"))
    except Exception:
        results.append((0, "error"))


async def run_burst(url: str, n: int, batch_size: int) -> tuple[list, float]:
    """
    Lance N requêtes concurrentes en batches.
    Retourne (résultats, temps_mur_total_secondes).

    Le temps mur est mesuré depuis l'envoi du premier batch jusqu'à la dernière réponse.
    """
    results: list = []
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    connector = aiohttp.TCPConnector(limit=batch_size, limit_per_host=batch_size)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Construire toutes les coroutines d'abord
        all_coros = [fetch_one(session, url, results) for _ in range(n)]

        # Démarrer le chrono juste avant le premier envoi
        t_start = time.perf_counter()

        # Envoyer en batches pour éviter les limites OS (descripteurs de fichiers)
        n_batches = (n + batch_size - 1) // batch_size
        for i in range(0, n, batch_size):
            batch = all_coros[i: i + batch_size]
            await asyncio.gather(*batch)

            done = min(i + batch_size, n)
            batch_num = i // batch_size + 1
            pct = done / n * 100
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            sys.stdout.write(f"\r  [{bar}] {pct:5.1f}%  batch {batch_num}/{n_batches}  ({done}/{n} req)")
            sys.stdout.flush()

        t_end = time.perf_counter()

    print()  # Saut de ligne après la barre de progression
    return results, t_end - t_start


def print_report(results: list, total_time: float, n: int, url: str) -> None:
    """Affiche le rapport de performance."""
    successes = [(s, r) for s, r in results if 200 <= s < 300]
    failures = len(results) - len(successes)
    effective_rps = n / total_time if total_time > 0 else 0

    print()
    print("=" * 68)
    print("  BURST TEST — RÉSULTATS")
    print("=" * 68)
    print(f"  URL cible        : {url}")
    print(f"  Requêtes totales : {n:,}")
    print(f"  Temps mur total  : {total_time:.3f}s")
    print(f"  RPS effectif     : {effective_rps:,.0f} req/s")
    print(f"  Succès (2xx)     : {len(successes):,}  ({len(successes) / n * 100:.1f}%)")
    print(f"  Échecs           : {failures:,}  ({failures / n * 100:.1f}%)")

    if failures > 0:
        error_counts = Counter(r for s, r in results if s == 0)
        for reason, count in error_counts.most_common():
            print(f"    ↳ {reason}: {count}")

    print("-" * 68)

    if successes:
        replica_counts = Counter(r for _, r in successes)
        n_replicas = len(replica_counts)
        print(f"  Distribution par réplique ({n_replicas} réplique(s) détectée(s)) :")
        total_ok = len(successes)
        for replica, count in sorted(replica_counts.items(), key=lambda x: -x[1]):
            pct = count / total_ok * 100
            bar = "█" * int(pct / 2.5)  # 40 chars max pour 100%
            print(f"    {replica:<28} {count:>6,}  ({pct:5.1f}%)  {bar}")
    else:
        print("  Aucune requête réussie — vérifiez l'URL et que l'app est démarrée.")

    print("=" * 68)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Burst test — mesure le temps total pour N requêtes simultanées",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python ops/burst_test.py
  python ops/burst_test.py --url http://localhost/health -n 10000
  python ops/burst_test.py --url http://localhost/api/v1/events/top/attack-categories -n 5000 --batch 500
  python ops/burst_test.py --url https://VOTRE_IP_GCP/health -n 10000 --batch 500
        """,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"URL cible (défaut: {DEFAULT_URL})",
    )
    parser.add_argument(
        "-n",
        type=int,
        default=DEFAULT_N,
        help=f"Nombre total de requêtes (défaut: {DEFAULT_N})",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=DEFAULT_BATCH,
        help=f"Taille des batches concurrents, évite les limites OS (défaut: {DEFAULT_BATCH})",
    )
    args = parser.parse_args()

    n_batches = (args.n + args.batch - 1) // args.batch
    print()
    print(f"  Burst Test — {args.n:,} requêtes simultanées")
    print(f"  URL     : {args.url}")
    print(f"  Batches : {n_batches} × {args.batch} requêtes concurrentes")
    print(f"  Timeout : {REQUEST_TIMEOUT}s par requête")
    print()

    results, total_time = asyncio.run(run_burst(args.url, args.n, args.batch))
    print_report(results, total_time, args.n, args.url)


if __name__ == "__main__":
    main()
