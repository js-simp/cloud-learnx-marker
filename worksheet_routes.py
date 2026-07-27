"""
worksheet_routes.py
────────────────────
FastAPI router for worksheet generation.
Mount this in your main.py with:
    from worksheet_routes import router as worksheet_router
    app.include_router(worksheet_router, prefix="/api/v1")
"""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from worksheet_generator import generate_worksheet

router  = APIRouter()
TIKZ_DIR = Path(__file__).parent / "tikz_samples"
OUT_DIR  = Path(__file__).parent / "output_worksheets"

# In-memory job store (share with main.py jobs dict in production)
worksheet_jobs = {}


class WorksheetRequest(BaseModel):
    student_profile: dict
    topic:           str
    board:           str = "Cloud LearnX"
    subject:         str = "Mathematics"


def run_worksheet_job(job_id: str, request: WorksheetRequest):
    """Background task that runs the generator and updates job status."""
    worksheet_jobs[job_id]["status"] = "Generating"
    try:
        result = generate_worksheet(
            student_profile  = request.student_profile,
            topic            = request.topic,
            tikz_samples_dir = TIKZ_DIR if TIKZ_DIR.exists() else None,
            output_dir       = OUT_DIR,
            board            = request.board,
            subject          = request.subject,
        )
        if result["success"]:
            worksheet_jobs[job_id]["status"]      = "Completed"
            worksheet_jobs[job_id]["pdf_path"]    = result["pdf_path"]
            worksheet_jobs[job_id]["mark_scheme"] = result["mark_scheme"]
            worksheet_jobs[job_id]["plan"]        = result["plan"]
        else:
            worksheet_jobs[job_id]["status"] = "Failed"
            worksheet_jobs[job_id]["error"]  = result["error"]
    except Exception as e:
        worksheet_jobs[job_id]["status"] = "Failed"
        worksheet_jobs[job_id]["error"]  = str(e)


@router.post("/worksheets/generate")
async def create_worksheet(
    request:          WorksheetRequest,
    background_tasks: BackgroundTasks,
    req:              Request,
):
    """Queue a worksheet generation job."""
    # Auth check
    token    = req.headers.get("Authorization", "").replace("Bearer ", "")
    # TODO: verify token against Supabase here (same as grade-paper endpoint)

    import uuid
    job_id = str(uuid.uuid4())[:8]
    worksheet_jobs[job_id] = {
        "status":      "Queued",
        "pdf_path":    None,
        "mark_scheme": None,
        "plan":        None,
        "error":       None,
    }
    background_tasks.add_task(run_worksheet_job, job_id, request)
    return {"job_id": job_id, "status": "Queued"}


@router.get("/worksheets/status/{job_id}")
async def worksheet_status(job_id: str):
    if job_id not in worksheet_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = worksheet_jobs[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "plan":   job.get("plan"),
        "error":  job.get("error"),
    }


@router.get("/worksheets/download/{job_id}")
async def download_worksheet(job_id: str):
    if job_id not in worksheet_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = worksheet_jobs[job_id]
    if job["status"] != "Completed" or not job["pdf_path"]:
        raise HTTPException(status_code=400, detail="Worksheet not ready yet")
    return FileResponse(
        job["pdf_path"],
        media_type="application/pdf",
        filename=Path(job["pdf_path"]).name,
    )


@router.get("/worksheets/markscheme/{job_id}")
async def get_mark_scheme(job_id: str):
    """Returns the mark scheme JSON — can be fed directly to the grader."""
    if job_id not in worksheet_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = worksheet_jobs[job_id]
    if job["status"] != "Completed" or not job["mark_scheme"]:
        raise HTTPException(status_code=400, detail="Mark scheme not ready yet")
    return job["mark_scheme"]
