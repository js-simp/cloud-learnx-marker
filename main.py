import os
import shutil
import uuid
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") # Service role key bypasses RLS for backend tasks
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Import your core engine
from pipeline import run_pipeline


# ── App Configuration ────────────────────────────────────────────────────────
app = FastAPI(
    title="Cloud LearnX Grading API",
    description="Asynchronous backend for bulk IGCSE Math grading.",
    version="1.0"
)

# Allow frontend applications (like React/Vue) to communicate with this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Update this to your exact frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Storage & State ──────────────────────────────────────────────────────────
# Create directories for temporary uploads and generated reports
UPLOAD_DIR = "temp_uploads"
REPORTS_DIR = "reports"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# In-memory dictionary to track background jobs
# Note: For multi-server production, move this to Redis or your SQLite DB
jobs = {}

# ── Background Task Runner ───────────────────────────────────────────────────
def process_grading_job(job_id: str, student_pdf_path: str, scheme_pdf_path: str):
    """Runs the AI pipeline in the background and updates the job status."""
    try:
        jobs[job_id]["status"] = "Processing"
        
        # Define where the final JSON report should be saved
        report_filename = f"report_{job_id}.json"
        report_path = os.path.join(REPORTS_DIR, report_filename)
        
        # Give this specific job its own folder for sliced question PDFs to avoid overlap
        job_output_dir = os.path.join(UPLOAD_DIR, f"sliced_pdfs_{job_id}")

        # Trigger the main AI grading engine using the EXACT arguments pipeline.py expects
        report_data = run_pipeline(
            student_pdf=student_pdf_path,
            scheme_pdf=scheme_pdf_path,
            output_dir=job_output_dir,
            report_path=report_path
        )

        # Update state on success, matching the exact keys from your generate_report() function
        jobs[job_id]["status"] = "Completed"
        jobs[job_id]["report_path"] = report_path
        jobs[job_id]["summary"] = {
            "paper_title": report_data.get("paper_title"),
            "total_marks_awarded": report_data["summary"].get("total_marks_awarded"),
            "total_marks_possible": report_data["summary"].get("total_marks_possible"),
            "percentage": report_data["summary"].get("percentage"),
            "questions_flagged": report_data["summary"].get("questions_flagged")
        }

    except Exception as e:
        # Catch errors so the server doesn't crash, and log them for debugging
        error_msg = str(e)
        print(f"🚨 Background Job {job_id} Failed:\n{traceback.format_exc()}")
        jobs[job_id]["status"] = "Failed"
        jobs[job_id]["error"] = error_msg

    finally:
        # Clean up the large PDF files from the server to save disk space
        if os.path.exists(student_pdf_path):
            os.remove(student_pdf_path)
        if os.path.exists(scheme_pdf_path):
            os.remove(scheme_pdf_path)

# ── API Endpoints ────────────────────────────────────────────────────────────

@app.get("/")
async def serve_homepage():
    """Serves the main frontend UI."""
    return FileResponse("index.html")

@app.post("/api/v1/grade-paper")
async def upload_and_grade(
    
    background_tasks: BackgroundTasks,
    student_paper: UploadFile = File(...),
    marking_scheme: UploadFile = File(...),
    token: str = Form(...) # Sent from index.html localStorage
):

    # 1. Verify user identity
    user_response = supabase_admin.auth.get_user(token)
    if not user_response or not user_response.user:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    
    user_id = user_response.user.id

    # 2. Check credit balance
    profile = supabase_admin.table("profiles").select("credits").eq("id", user_id).single().execute()
    credits = profile.data.get("credits", 0)

    if credits < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits. Please top up using PayHere.")

    # 3. Deduct 1 credit
    supabase_admin.table("profiles").update({"credits": credits - 1}).eq("id", user_id).execute()

    """
    Accepts two PDFs from the tutor, saves them temporarily, 
    and kicks off the grading pipeline in the background.
    """
    # 1. Validate file types
    if not student_paper.filename.lower().endswith('.pdf') or not marking_scheme.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Both files must be PDFs.")

    # 2. Generate a unique job ID
    job_id = str(uuid.uuid4())[:8]
    
    # 3. Save files securely with unique names to prevent overlap during bulk runs
    student_path = os.path.join(UPLOAD_DIR, f"{job_id}_{student_paper.filename}")
    scheme_path = os.path.join(UPLOAD_DIR, f"{job_id}_{marking_scheme.filename}")
    
    with open(student_path, "wb") as buffer:
        shutil.copyfileobj(student_paper.file, buffer)
    with open(scheme_path, "wb") as buffer:
        shutil.copyfileobj(marking_scheme.file, buffer)

    # 4. Register the job in memory
    jobs[job_id] = {
        "status": "Queued",
        "student_file": student_paper.filename,
        "report_path": None,
        "error": None
    }

    # 5. Hand the heavy lifting to the background task
    background_tasks.add_task(process_grading_job, job_id, student_path, scheme_path)

    return {
        "message": "Grading job successfully queued.",
        "job_id": job_id,
        "status": "Queued"
    }

@app.get("/api/v1/status/{job_id}")
async def check_status(job_id: str):
    """
    Frontend polls this endpoint every few seconds to show a progress bar.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {"job_id": job_id, "details": jobs[job_id]}