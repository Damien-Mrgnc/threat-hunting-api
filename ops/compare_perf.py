import subprocess
import re
import sys
import os
import time

# Script Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOGGLE_SCRIPT = os.path.join(BASE_DIR, "toggle_perf.py")
BENCHMARK_SCRIPT = os.path.join(BASE_DIR, "benchmark.py")

def run_command(cmd_args, capture=False):
    """Runs a python script as a subprocess."""
    try:
        python_exe = sys.executable
        full_cmd = [python_exe] + cmd_args
        
        if capture:
            # Capture output for parsing
            result = subprocess.run(full_cmd, capture_output=True, text=True, check=True)
            return result.stdout
        else:
            # Let it print to stdout/stderr normally
            subprocess.run(full_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Error running {' '.join(cmd_args)}: {e}")
        if capture:
            print("STDOUT:", e.stdout)
            print("STDERR:", e.stderr)
        sys.exit(1)

def parse_benchmark_output(output):
    """Parses the text output of benchmark.py."""
    data = {}
    
    # Extract numbers using regex
    # Format matches benchmark.py output: "Total execution time: 0.5150 seconds"
    time_pat = re.search(r"Total execution time: ([0-9\.]+) seconds", output)
    avg_pat = re.search(r"avg: ([0-9\.]+)", output)
    p50_pat = re.search(r"p50: ([0-9\.]+)", output)
    p95_pat = re.search(r"p95: ([0-9\.]+)", output)
    p99_pat = re.search(r"p99: ([0-9\.]+)", output)
    
    if time_pat: data['total_time'] = float(time_pat.group(1))
    if avg_pat: data['avg'] = float(avg_pat.group(1))
    if p50_pat: data['p50'] = float(p50_pat.group(1))
    if p95_pat: data['p95'] = float(p95_pat.group(1))
    if p99_pat: data['p99'] = float(p99_pat.group(1))
    
    return data

def main():
    print("=========================================")
    print("⚡ AUTOMATED PERFORMANCE COMPARISON ⚡")
    print("=========================================")
    print("This script will run the benchmark in both OFF and ON modes")
    print("and calculate the speedup factor.\n")

    # ---------------------------------------------------------
    # 1. BASELINE (OFF)
    # ---------------------------------------------------------
    print("[1/4] 🐢 Switching to BASELINE mode (Optimizations OFF)...")
    run_command([TOGGLE_SCRIPT, "off"], capture=False)
    
    print("\n[2/4] ⏱️  Running Benchmark (Baseline)...")
    print("       (Please wait, this might take a few seconds...)")
    baseline_output = run_command([BENCHMARK_SCRIPT], capture=True)
    baseline_data = parse_benchmark_output(baseline_output)
    
    if not baseline_data.get('total_time'):
        print("❌ Failed to parse baseline benchmark results.")
        print(baseline_output)
        sys.exit(1)
        
    print(f"       ✅ Baseline Done. Total Time: {baseline_data['total_time']:.4f}s")

    # ---------------------------------------------------------
    # 2. OPTIMIZED (ON)
    # ---------------------------------------------------------
    print("\n[3/4] 🚀 Switching to HIGH PERFORMANCE mode (Optimizations ON)...")
    run_command([TOGGLE_SCRIPT, "on"], capture=False)
    
    print("\n[4/4] ⏱️  Running Benchmark (Optimized)...")
    opt_output = run_command([BENCHMARK_SCRIPT], capture=True)
    opt_data = parse_benchmark_output(opt_output)

    if not opt_data.get('total_time'):
        print("❌ Failed to parse optimized benchmark results.")
        print(opt_output)
        sys.exit(1)

    print(f"       ✅ Optimized Done. Total Time: {opt_data['total_time']:.4f}s")

    # ---------------------------------------------------------
    # 3. REPORT
    # ---------------------------------------------------------
    print("\n" + "="*75)
    print(f"{'METRIC':<20} | {'🐢 BASELINE':<15} | {'🚀 OPTIMIZED':<15} | {'🏆 IMPROVEMENT'}")
    print("-" * 75)
    
    metrics = [
        ("Total Time (50 req)", "total_time"),
        ("Avg Latency", "avg"),
        ("p50 Latency", "p50"),
        ("p95 Latency", "p95"),
        ("p99 Latency", "p99")
    ]
    
    for label, key in metrics:
        val_base = baseline_data.get(key, 0.0)
        val_opt = opt_data.get(key, 0.0)
        
        # Avoid division by zero
        if val_opt > 0 and val_base > 0:
            speedup = val_base / val_opt
            if speedup >= 1:
                improv_str = f"✅ {speedup:.1f}x FASTER"
            else:
                improv_str = f"❌ {val_opt/val_base:.1f}x SLOWER"
        elif val_opt == 0:
            improv_str = "∞ FASTER"
        else:
            improv_str = "N/A"
            
        print(f"{label:<20} | {val_base:.6f}s       | {val_opt:.6f}s       | {improv_str}")
        
    print("="*75)
    print("Comparison Complete.")

if __name__ == "__main__":
    main()
