import os
import redis

# --- Redis Connection ---
# We use a global connection. In prod, use a dependency or pool management.
try:
    REDIS_URL = os.getenv("REDIS_URL", f"redis://{os.getenv('REDIS_HOST', 'redis')}:6379")
    r = redis.Redis.from_url(REDIS_URL, db=0, decode_responses=True)
    r.ping() # Fail fast if no redis
    print("✅ Connected to Redis")
except Exception as e:
    print(f"⚠️ Redis connection failed: {e}")
    r = None

def get_redis():
    return r
