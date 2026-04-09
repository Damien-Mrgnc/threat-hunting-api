from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import time
from sqlalchemy import create_engine
from core.database import engine

# --- Prometheus metrics ---

REQ_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["path", "method", "status"],
)

REQ_LAT = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["path", "method"],
)

DB_CONN = Gauge(
    "db_pool_checked_out_connections",
    "Checked-out DB connections from SQLAlchemy pool",
)

# Security metrics
ML_DETECT_TOTAL = Counter(
    "ml_detections_total",
    "Total network events classified by the ML model",
    ["label"],
)

THREAT_INTEL_HITS_TOTAL = Counter(
    "threat_intel_hits_total",
    "Total IPs flagged as malicious by AbuseIPDB",
    ["country"],
)

async def metrics_middleware(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    dur = time.perf_counter() - start

    path = request.url.path
    REQ_LAT.labels(path=path, method=request.method).observe(dur)
    REQ_COUNT.labels(path=path, method=request.method, status=str(response.status_code)).inc()

    # SQLAlchemy pool: how many connections are currently checked out
    try:
        # We check this BEFORE returning the response to capture the connection used by THIS request
        DB_CONN.set(engine.pool.checkedout())
    except Exception:
        pass

    return response
