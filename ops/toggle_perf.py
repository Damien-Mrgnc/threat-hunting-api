import requests
import subprocess
import argparse
import time
import os

API_URL = "http://localhost:8000"
DB_CONTAINER = "threat-db"
DB_USER = "analyst_user"
DB_NAME = "threat_hunting_db"

import os

def run_db_script(script_path):
    # Construct absolute path to the SQL file on the host
    # Assumes this script is in ops/ and sql files are in db/
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_path = os.path.join(base_dir, "db", script_path)
    
    print(f"> Reading SQL file: {file_path}")
    try:
        with open(file_path, "r") as f:
            sql_content = f.read()
            
        cmd = [
            "docker", "exec", "-i", DB_CONTAINER, 
            "psql", "-U", DB_USER, "-d", DB_NAME
        ]
        
        print(f"> Executing SQL: {script_path} inside container via stdin...")
        subprocess.run(cmd, input=sql_content, text=True, check=True)
        print("✅ Database updated.")
    except FileNotFoundError:
        print(f"❌ SQL file not found: {file_path}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Database error: {e}")

def set_api_config(use_redis):
    url = f"{API_URL}/config/features"
    try:
        requests.post(url, json={"use_redis": use_redis})
        print(f"✅ API Configuration updated: use_redis={use_redis}")
    except Exception as e:
        print(f"❌ API Error: {e}")

def main():
    parser = argparse.ArgumentParser(description="Toggle Performance Optimizations")
    parser.add_argument("mode", choices=["on", "off"], help="Enable or Disable optimizations")
    
    args = parser.parse_args()
    
    if args.mode == "on":
        print("\n🚀 ACTIVATING HIGH PERFORMANCE MODE...")
        print("-" * 40)
        # 1. Enable SQL Indexes & Views
        run_db_script("optimize.sql")
        # 2. Enable Redis
        set_api_config(True)
        print("-" * 40)
        print("🔥 SYSTEM OPTIMIZED. READY FOR LOAD.\n")
        
    else:
        print("\n🐢 DEACTIVATING OPTIMIZATIONS (BASELINE MODE)...")
        print("-" * 40)
        # 1. Drop Indexes & Views
        run_db_script("deoptimize.sql")
        # 2. Disable Redis
        set_api_config(False)
        print("-" * 40)
        print("📉 SYSTEM RESET TO BASELINE. EXPECT LATENCY.\n")

if __name__ == "__main__":
    main()
