import os
import threading
import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.database import engine
from core.observability import metrics_middleware
from routers import events, reports, jobs, system, auth, detect
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Initialize Rate Limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Threat Hunting API (Optimized + Secured)")

@app.middleware("http")
async def add_process_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-API-Replica"] = os.getenv("K_REVISION", os.getenv("HOSTNAME", "unknown"))
    return response

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- CORS & Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)
app.middleware("http")(metrics_middleware)

# --- Static Files ---
try:
    # Interface path: ../interface relative to this file
    interface_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "interface"))
    if os.path.exists(interface_path):
        app.mount("/interface", StaticFiles(directory=interface_path, html=True), name="interface")
except Exception as e:
    print(f"Warning: Interface could not be mounted: {e}")

# Mount reports directory
reports_path = os.path.join(os.path.dirname(__file__), "reports")
os.makedirs(reports_path, exist_ok=True)
app.mount("/downloads", StaticFiles(directory=reports_path), name="reports")

# --- Routers ---
app.include_router(auth.router, prefix="/auth", tags=["Security"])
app.include_router(system.router)
app.include_router(events.router, prefix="/events", tags=["Events"])
app.include_router(reports.router, prefix="/reports", tags=["Reports"])
app.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])
app.include_router(detect.router)

def _refresh_materialized_views():
    """Rafraîchit les vues matérialisées toutes les 5 minutes en arrière-plan."""
    while True:
        time.sleep(300)
        try:
            db = Session(engine)
            db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_network_stats_proto"))
            db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_attack_categories"))
            db.commit()
            db.close()
        except Exception as e:
            print(f"⚠️  Refresh vues matérialisées échoué : {e}")


# --- Startup Events ---
@app.on_event("startup")
def cleanup_stuck_jobs():
    """
    Reset jobs stuck in 'processing' state during restart to 'failed'.
    """
    try:
        # Create a new standalone session because 'db' dependency isn't available here
        db = Session(engine)
        
        # Find jobs that were processing when the server stopped/crashed
        result = db.execute(text("UPDATE jobs SET status = 'failed', error_message = 'Interrupted by server restart' WHERE status = 'processing'"))
        db.commit()
        
        if result.rowcount > 0:
            print(f"⚠️  Cleaned up {result.rowcount} stuck jobs from previous run.")
        else:
            print("✅ No stuck jobs found on startup.")

        db.close()
    except Exception as e:
        print(f"❌ Error cleaning up jobs: {e}")

    threading.Thread(target=_refresh_materialized_views, daemon=True).start()
    print("✅ Background refresh des vues matérialisées démarré (toutes les 5 min).")
