import os
import time
import json
import calendar
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from core.database import engine

def run_analysis_job(job_id: str, job_type: str, params: dict):
    """
    Generic worker function to run heavy analysis jobs and save results as JSON.
    Supported job_types: 'monthly_report', 'event_search', 'traffic_stats'
    """
    # Reports path logic
    reports_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
    os.makedirs(reports_path, exist_ok=True)
    
    db = Session(engine)
    filename = f"{job_type}_{job_id}.json"
    filepath = os.path.join(reports_path, filename)
    
    try:
        # Update status
        db.execute(text("UPDATE jobs SET status = 'processing' WHERE job_id = :job_id"), {"job_id": job_id})
        db.commit()
        
        print(f"[{job_id}] Starting {job_type} with params: {params}...")
        start_time = time.time()
        
        results = []
        
        # --- LOGIC DISPATCHER ---
        if job_type == 'monthly_report':
            year = int(params.get('year', 2024))
            month = int(params.get('month', 1))
            last_day = calendar.monthrange(year, month)[1]
            month_start = datetime(year, month, 1)
            month_end = datetime(year, month, last_day, 23, 59, 59, 999999)

            sql = text("""
                SELECT srcip,
                       COUNT(*) as total_events,
                       SUM(sbytes) as total_bytes,
                       array_agg(DISTINCT attack_cat) as attack_types
                FROM network_events
                WHERE ts >= :month_start AND ts <= :month_end
                GROUP BY srcip
                ORDER BY total_bytes DESC
                LIMIT 50
            """)
            rows = db.execute(sql, {"month_start": month_start, "month_end": month_end}).mappings().all()
            for r in rows:
                item = dict(r)
                # Clean arrays for JSON serialization
                item['attack_types'] = [a for a in item['attack_types'] if a]
                results.append(item)
                
        elif job_type == 'event_search':
            # Dynamic construction of search query (same as in router)
            query_parts = ["SELECT ts, srcip, dstip, proto, service, sbytes, attack_cat, label FROM network_events WHERE srcip = :srcip"]
            # Default srcip must be present in params
            query_params = {"srcip": params.get("srcip"), "offset": params.get("offset", 0)}

            if params.get("from_ts"):
                query_parts.append("AND ts >= :from_ts")
                query_params["from_ts"] = params["from_ts"]
            if params.get("to_ts"):
                query_parts.append("AND ts < :to_ts")
                query_params["to_ts"] = params["to_ts"]
            if params.get("proto"):
                query_parts.append("AND proto = :proto")
                query_params["proto"] = params["proto"]
            if params.get("service"):
                query_parts.append("AND service = :service")
                query_params["service"] = params["service"]
            if params.get("label"):
                query_parts.append("AND label = :label")
                query_params["label"] = params["label"]

            query_parts.append("ORDER BY ts DESC")

            limit = params.get("limit")
            if limit:
                query_parts.append("LIMIT :limit")
                query_params["limit"] = limit
            
            query_parts.append("OFFSET :offset")
            
            sql = text(" ".join(query_parts))
            rows = db.execute(sql, query_params).mappings().all()
            results = [dict(r) for r in rows]
            
        elif job_type == 'traffic_stats':
            # Placeholder for future stats implementation
            pass

        elapsed = time.time() - start_time
        
        # --- JSON OUTPUT ---
        output_data = {
            "meta": {
                "job_id": job_id,
                "type": job_type,
                "generated_at": datetime.now().isoformat(),
                "compute_time_sec": round(elapsed, 4),
                "params": params
            },
            "data": results
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, default=str)
            
        # Update status
        db.execute(
            text("UPDATE jobs SET status = 'completed', completed_at = NOW(), result_path = :path WHERE job_id = :job_id"),
            {"path": f"/downloads/{filename}", "job_id": job_id}
        )
        db.commit()
        print(f"[{job_id}] Job completed successfully.")
        
    except Exception as e:
        print(f"[{job_id}] Failed: {e}")
        db.execute(
            text("UPDATE jobs SET status = 'failed', completed_at = NOW(), error_message = :msg WHERE job_id = :job_id"),
            {"msg": str(e), "job_id": job_id}
        )
        db.commit()
    finally:
        db.close()
