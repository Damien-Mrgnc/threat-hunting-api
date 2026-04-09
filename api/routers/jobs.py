from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from core.database import get_db
from core.auth import get_current_active_analyst, get_current_admin

router = APIRouter()

@router.get("/")
def list_jobs(limit: int = 10, db: Session = Depends(get_db), current_user: dict = Depends(get_current_active_analyst)):
    """List recent jobs for the dashboard"""
    sql = text("SELECT * FROM jobs ORDER BY submitted_at DESC LIMIT :limit")
    rows = db.execute(sql, {"limit": limit}).mappings().all()
    
    # Convert rows to list of dicts with ISO format dates
    jobs = []
    for row in rows:
        job = dict(row)
        if job.get("submitted_at"):
            job["submitted_at"] = job["submitted_at"].isoformat()
        if job.get("completed_at"):
            job["completed_at"] = job["completed_at"].isoformat()
        jobs.append(job)
        
    return jobs

@router.get("/{job_id}")
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    sql = text("SELECT * FROM jobs WHERE job_id = :job_id")
    row = db.execute(sql, {"job_id": job_id}).mappings().first()
    
    if not row:
        return {"error": "Job not found"}
    
    job_data = dict(row)
    if job_data.get("submitted_at"):
        job_data["submitted_at"] = job_data["submitted_at"].isoformat()
    if job_data.get("completed_at"):
        job_data["completed_at"] = job_data["completed_at"].isoformat()
        
    return job_data
