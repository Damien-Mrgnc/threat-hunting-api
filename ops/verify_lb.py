import requests
import time
import argparse
from collections import Counter
import sys

def verify_load_balancing(url, count=50, delay=0.1):
    print(f"Testing Load Balancing against {url}")
    print(f"Sending {count} requests with {delay}s delay...")
    
    replicas = []
    errors = 0
    
    for i in range(count):
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                replica_id = response.headers.get("X-API-Replica", "Unknown")
                replicas.append(replica_id)
                sys.stdout.write(".")
            else:
                sys.stdout.write("E")
                errors += 1
        except Exception as e:
            sys.stdout.write("X")
            errors += 1
        
        sys.stdout.flush()
        time.sleep(delay)
    
    print("\n\n--- Load Balancing Report ---")
    print(f"Total Requests: {count}")
    print(f"Successful: {len(replicas)}")
    print(f"Failed: {errors}")
    
    if replicas:
        counts = Counter(replicas)
        print("\nDistribution by Replica:")
        for replica, c in counts.most_common():
            percentage = (c / len(replicas)) * 100
            print(f"  {replica}: {c} requests ({percentage:.1f}%)")
            
        print("\nAnalysis:")
        if len(counts) > 1:
            print("✅ Traffic is being distributed across multiple replicas.")
        else:
            print("⚠️  Traffic is handled by a SINGLE replica only.")
    else:
        print("❌ No successful responses obtained.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify Load Balancing Distribution")
    parser.add_argument("--url", default="http://localhost:80/system/health", help="Target URL")
    parser.add_argument("--count", type=int, default=50, help="Number of requests")
    parser.add_argument("--delay", type=float, default=0.05, help="Delay between requests")
    
    args = parser.parse_args()
    
    verify_load_balancing(args.url, args.count, args.delay)
