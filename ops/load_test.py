import requests
import concurrent.futures
import time
import argparse
import statistics
import sys
from collections import Counter

# Configuration defaults
DEFAULT_URL = "http://localhost/api/health"
DEFAULT_REQUESTS = 1000
DEFAULT_CONCURRENCY = 50
TIMEOUT = 5

def send_request(url):
    """
    Sends a request and returns (status_code, elapsed_time, replica_id)
    """
    try:
        start_time = time.time()
        resp = requests.get(url, timeout=TIMEOUT)
        elapsed = time.time() - start_time
        replica = resp.headers.get("X-API-Replica", "Unknown")
        return resp.status_code, elapsed, replica
    except Exception as e:
        return 0, 0.0, "Error"

def main():
    parser = argparse.ArgumentParser(description="API Load Testing Tool")
    parser.add_argument("--url", default=DEFAULT_URL, help="Target URL")
    parser.add_argument("-n", "--requests", type=int, default=DEFAULT_REQUESTS, help="Total number of requests")
    parser.add_argument("-c", "--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Number of concurrent threads")
    
    args = parser.parse_args()

    print(f"Starting Load Test on {args.url}")
    print(f"Requests: {args.requests}, Concurrency: {args.concurrency}")
    print("-" * 60)

    results = []
    start_global = time.time()

    # ThreadPool for concurrency
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(send_request, args.url) for _ in range(args.requests)]
        
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            completed += 1
            if completed % (args.requests // 10) == 0:
                sys.stdout.write(f"\rProgress: {completed}/{args.requests} ({completed/args.requests*100:.0f}%)")
                sys.stdout.flush()

    print("\n" + "-" * 60)
    end_global = time.time()
    total_time = end_global - start_global
    rps = args.requests / total_time

    # Process Results
    successes = [r for r in results if 200 <= r[0] < 300]
    failures = len(results) - len(successes)
    latencies = [r[1] for r in successes]
    replicas = [r[2] for r in successes]

    print(f"Total Time: {total_time:.4f}s")
    print(f"Requests per Second (RPS): {rps:.2f}")
    print(f"Success Rate: {len(successes)/args.requests*100:.2f}% ({len(successes)}/{args.requests})")
    print(f"Failures: {failures}")
    
    if latencies:
        avg_lat = statistics.mean(latencies)
        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]

        print("\nLatency Metrics (seconds):")
        print(f"  Avg: {avg_lat:.4f}")
        print(f"  P50: {p50:.4f}")
        print(f"  P95: {p95:.4f}")
        print(f"  P99: {p99:.4f}")

    if replicas:
        print("\nReplica Distribution:")
        counts = Counter(replicas)
        total_valid = len(replicas)
        for replica, count in counts.most_common():
            print(f"  {replica}: {count} ({count/total_valid*100:.1f}%)")

if __name__ == "__main__":
    main()
