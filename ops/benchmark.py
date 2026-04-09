import requests
import concurrent.futures
import time
import argparse
import statistics

# Configuration defaults
DEFAULT_URL = "http://localhost:8000/events/stats/bytes-by-proto"
DEFAULT_REQUESTS = 50
DEFAULT_CONCURRENCY = 10
TIMEOUT = 30

def send_request(url):
    """
    Sends a request and returns (status_code, elapsed_time)
    """
    try:
        start_time = time.time()
        resp = requests.get(url, timeout=TIMEOUT)
        elapsed = time.time() - start_time
        return resp.status_code, elapsed
    except Exception as e:
        return 0, 0.0

def main():
    parser = argparse.ArgumentParser(description="API Benchmark Tool (int.sh adaptation)")
    parser.add_argument("--url", default=DEFAULT_URL, help="Target URL")
    parser.add_argument("-n", "--requests", type=int, default=DEFAULT_REQUESTS, help="Total number of requests")
    parser.add_argument("-c", "--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Number of concurrent threads")
    
    args = parser.parse_args()

    print(f"Sending {args.requests} requests to:")
    print(f"  {args.url}")
    print(f"Concurrency: {args.concurrency}")
    print("-" * 40)

    results = []
    start_global = time.time()

    # ThreadPool for concurrency
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(send_request, args.url) for _ in range(args.requests)]
        
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    end_global = time.time()
    total_time = end_global - start_global

    # Process Results
    successes = [r for r in results if 200 <= r[0] < 300]
    failures = len(results) - len(successes)
    latencies = [r[1] for r in successes]

    print("-" * 40)
    print(f"Total execution time: {total_time:.4f} seconds")
    print(f"2xx responses: {len(successes)} / {args.requests}")
    print(f"Failures: {failures} / {args.requests}")
    
    if latencies:
        avg_lat = statistics.mean(latencies)
        try:
            # Python 3.8+ has quantiles, else manual
            quantiles = statistics.quantiles(latencies, n=100) if hasattr(statistics, 'quantiles') else []
            p50 = quantiles[49] if quantiles else statistics.median(latencies)
            p95 = quantiles[94] if quantiles else latencies[int(len(latencies)*0.95)]
            p99 = quantiles[98] if quantiles else latencies[int(len(latencies)*0.99)]
        except:
             # Fallback for simpler calculation
             sorted_lat = sorted(latencies)
             p50 = sorted_lat[int(len(sorted_lat) * 0.50)]
             p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
             p99 = sorted_lat[int(len(sorted_lat) * 0.99)]

        print("Latency (2xx only, seconds):")
        print(f"  avg: {avg_lat:.6f}")
        print(f"  p50: {p50:.6f}")
        print(f"  p95: {p95:.6f}")
        print(f"  p99: {p99:.6f}")
    else:
        print("Latency: N/A (No successful requests)")

if __name__ == "__main__":
    main()
