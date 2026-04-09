from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from core.database import get_db
from core.auth import get_current_active_analyst
from services.reporting import run_analysis_job
from datetime import datetime
import uuid

router = APIRouter()

@router.post("/malicious-events")
def request_malicious_events_report(
    background_tasks: BackgroundTasks,
    year: int = 2023, 
    month: int = 1,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_active_analyst)
):
    job_id = str(uuid.uuid4())
    
    # Create persistent job record
    sql = text("""
        INSERT INTO jobs (job_id, status) 
        VALUES (:job_id, 'pending')
    """)
    db.execute(sql, {"job_id": job_id})
    db.commit()
    
    # Offload the task to the background
    params = {"year": year, "month": month}
    background_tasks.add_task(run_analysis_job, job_id, "monthly_report", params)
    
    return {"job_id": job_id, "message": "Report generation started", "status_url": f"/jobs/{job_id}"} 
