import os
import shutil
import uuid
import hashlib
import hmac
import traceback
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Form, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from typing import Optional

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
PAYHERE_MERCHANT_ID     = os.getenv("PAYHERE_MERCHANT_ID")
PAYHERE_MERCHANT_SECRET = os.getenv("PAYHERE_MERCHANT_SECRET")
PAYHERE_SANDBOX         = os.getenv("PAYHERE_SANDBOX", "true").lower() == "true"
BASE_URL                = os.getenv("BASE_URL", "http://localhost:8000")

supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

from pipeline import run_pipeline
from worksheet_generator import generate_worksheet
from adapter import normalize_student_profile

# ── App Configuration ────────────────────────────────────────────────────────
app = FastAPI(
    title="Cloud LearnX Grading API",
    version="1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR      = "temp_uploads"
REPORTS_DIR     = "reports"
WORKSHEETS_DIR  = "generated_worksheets"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(WORKSHEETS_DIR, exist_ok=True)

# In-memory job store (move to Redis/DB for multi-server production)
jobs = {}

# ── PayHere Hash Helpers ─────────────────────────────────────────────────────

def generate_payhere_hash(order_id: str, amount: str, currency: str) -> str:
    """
    PayHere hash formula:
    MD5( merchant_id + order_id + amount + currency + MD5(secret).upper() ).upper()
    """
    secret_hash = hashlib.md5(PAYHERE_MERCHANT_SECRET.encode()).hexdigest().upper()
    raw         = f"{PAYHERE_MERCHANT_ID}{order_id}{amount}{currency}{secret_hash}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def verify_payhere_notification(
    merchant_id, order_id, payhere_amount,
    payhere_currency, status_code, md5sig
) -> bool:
    """Verify incoming PayHere webhook signature."""
    secret_hash  = hashlib.md5(PAYHERE_MERCHANT_SECRET.encode()).hexdigest().upper()
    raw          = f"{merchant_id}{order_id}{payhere_amount}{payhere_currency}{status_code}{secret_hash}"
    expected_sig = hashlib.md5(raw.encode()).hexdigest().upper()
    return hmac.compare_digest(expected_sig, md5sig.upper())


# ── Background Task ──────────────────────────────────────────────────────────

def process_grading_job(
    job_id:          str,
    student_pdf_path: str,
    scheme_pdf_path:  str,
    user_id:         str,
):
    """Runs the AI pipeline in the background and updates job status."""
    try:
        jobs[job_id]["status"] = "Processing"

        report_filename = f"report_{job_id}.json"
        report_path     = os.path.join(REPORTS_DIR, report_filename)
        job_output_dir  = os.path.join(UPLOAD_DIR, f"sliced_pdfs_{job_id}")

        report_data = run_pipeline(
            student_pdf=student_pdf_path,
            scheme_pdf=scheme_pdf_path,
            output_dir=job_output_dir,
            report_path=report_path
        )

        # Only deduct credit AFTER successful completion
        profile = supabase_admin.table("profiles").select("credits").eq("id", user_id).single().execute()
        current = profile.data.get("credits", 0)
        supabase_admin.table("profiles").update({"credits": current - 1}).eq("id", user_id).execute()

        jobs[job_id]["status"]      = "Completed"
        jobs[job_id]["report_path"] = report_path
        jobs[job_id]["summary"]     = {
            "paper_title":         report_data.get("paper_title"),
            "total_marks_awarded":  report_data["summary"].get("total_marks_awarded"),
            "total_marks_possible": report_data["summary"].get("total_marks_possible"),
            "percentage":           report_data["summary"].get("percentage"),
            "questions_flagged":    report_data["summary"].get("questions_flagged"),
        }

    except Exception as e:
        print(f"🚨 Job {job_id} failed:\n{traceback.format_exc()}")
        jobs[job_id]["status"] = "Failed"
        jobs[job_id]["error"]  = str(e)

        # Refund the credit check — credit was NOT yet deducted (deduction moved to success path)

    finally:
        for path in [student_pdf_path, scheme_pdf_path]:
            if os.path.exists(path):
                os.remove(path)


# ── Background Task: Worksheet Generation ────────────────────────────────────

def process_worksheet_job(
    job_id:              str,
    student_id:          str,
    topic:                str,
    curriculum_override: Optional[str],
    user_id:              str,
):
    """Runs the worksheet generator in the background and updates job status."""
    try:
        jobs[job_id]["status"] = "Processing"

        profile_res = supabase_admin.table("student_profiles") \
            .select("profile_data, student_name") \
            .eq("id", student_id) \
            .single().execute()

        if not profile_res.data:
            raise ValueError(f"No student profile found for id='{student_id}'")

        raw_profile = profile_res.data["profile_data"]
        profile     = normalize_student_profile(raw_profile, topic=topic)

        # Manual curriculum override — falls back to whatever the student's own
        # profile carries (via CURRICULUM_MAP) if left blank. Safe either way:
        # curriculum_loader.py returns gracefully (no crash) if the id has no
        # matching file in curricula/, it just skips curriculum constraints.
        if curriculum_override:
            profile["curriculum_id"] = curriculum_override

        result = generate_worksheet(
            student_profile=profile,
            topic=topic,
            output_dir=WORKSHEETS_DIR,
        )

        if not result["success"]:
            raise RuntimeError(result["error"] or "Worksheet generation failed")

        # Only deduct credit AFTER successful completion — same pattern as grading
        credit_profile = supabase_admin.table("profiles").select("credits").eq("id", user_id).single().execute()
        current = credit_profile.data.get("credits", 0)
        supabase_admin.table("profiles").update({"credits": current - 1}).eq("id", user_id).execute()

        mark_scheme = result["mark_scheme"] or {}

        jobs[job_id]["status"]   = "Completed"
        jobs[job_id]["pdf_path"] = result["pdf_path"]
        jobs[job_id]["user_id"]  = user_id
        jobs[job_id]["summary"]  = {
            "student_name":  profile.get("name"),
            "topic":         topic,
            "num_questions": len(mark_scheme.get("questions", [])),
            "total_marks":   mark_scheme.get("total_marks"),
        }

    except Exception as e:
        print(f"🚨 Worksheet job {job_id} failed:\n{traceback.format_exc()}")
        jobs[job_id]["status"] = "Failed"
        jobs[job_id]["error"]  = str(e)


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/")
async def serve_homepage():
    return FileResponse("index.html")


@app.get("/api/v1/payhere-hash")
async def get_payhere_hash(request: Request):
    """
    Frontend calls this BEFORE submitting the PayHere form.
    Generates the required hash server-side (merchant secret never reaches browser).
    """
    token   = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_res = supabase_admin.auth.get_user(token)
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id  = user_res.user.id
    order_id = f"CREDITS_{user_id}"   # user_id embedded so webhook can identify them
    amount   = "10000.00"
    currency = "LKR"

    return {
        "merchant_id": PAYHERE_MERCHANT_ID,
        "order_id":    order_id,
        "amount":      amount,
        "currency":    currency,
        "hash":        generate_payhere_hash(order_id, amount, currency),
        "notify_url":  f"{BASE_URL}/api/v1/webhooks/payhere",
        "return_url":  f"{BASE_URL}/",
        "cancel_url":  f"{BASE_URL}/",
    }


@app.post("/api/v1/grade-paper")
async def upload_and_grade(
    background_tasks: BackgroundTasks,
    student_paper:    UploadFile = File(...),
    marking_scheme:   UploadFile = File(...),
    token:            str        = Form(...),
):
    # 1. Verify user
    user_res = supabase_admin.auth.get_user(token)
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    user_id = user_res.user.id

    # 2. Check credits (do NOT deduct yet — deduct only on success)
    profile = supabase_admin.table("profiles").select("credits").eq("id", user_id).single().execute()
    credits = profile.data.get("credits", 0)
    if credits < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits. Please top up.")

    # 3. Validate files
    if (not student_paper.filename.lower().endswith(".pdf") or
            not marking_scheme.filename.lower().endswith(".pdf")):
        raise HTTPException(status_code=400, detail="Both files must be PDFs.")

    # 4. Save files
    job_id       = str(uuid.uuid4())[:8]
    student_path = os.path.join(UPLOAD_DIR, f"{job_id}_student.pdf")
    scheme_path  = os.path.join(UPLOAD_DIR, f"{job_id}_scheme.pdf")

    with open(student_path, "wb") as f:
        shutil.copyfileobj(student_paper.file, f)
    with open(scheme_path, "wb") as f:
        shutil.copyfileobj(marking_scheme.file, f)

    # 5. Register job
    jobs[job_id] = {
        "status":      "Queued",
        "user_id":     user_id,
        "report_path": None,
        "error":       None,
    }

    # 6. Queue background task (passes user_id so it can deduct on success)
    background_tasks.add_task(
        process_grading_job, job_id, student_path, scheme_path, user_id
    )

    return {"message": "Grading job queued.", "job_id": job_id, "status": "Queued"}


@app.get("/api/v1/status/{job_id}")
async def check_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job_id": job_id, "details": jobs[job_id]}


@app.get("/api/v1/students")
async def list_students(request: Request):
    """Returns existing student profiles for the worksheet-generator dropdown."""
    token    = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_res = supabase_admin.auth.get_user(token)
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    res = supabase_admin.table("student_profiles") \
        .select("id, student_name, year_group") \
        .order("student_name") \
        .execute()

    return {"students": res.data or []}


@app.post("/api/v1/generate-worksheet")
async def generate_worksheet_endpoint(
    background_tasks: BackgroundTasks,
    student_id:        str           = Form(...),
    topic:              str           = Form(...),
    curriculum_id:      Optional[str] = Form(None),
    token:              str           = Form(...),
):
    # 1. Verify user
    user_res = supabase_admin.auth.get_user(token)
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    user_id = user_res.user.id

    # 2. Check credits (do NOT deduct yet — deduct only on success)
    profile = supabase_admin.table("profiles").select("credits").eq("id", user_id).single().execute()
    credits = profile.data.get("credits", 0)
    if credits < 1:
        raise HTTPException(status_code=402, detail="Insufficient credits. Please top up.")

    # 3. Validate inputs
    if not student_id.strip() or not topic.strip():
        raise HTTPException(status_code=400, detail="Student and topic are required.")

    # 4. Register job
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status":      "Queued",
        "user_id":     user_id,
        "pdf_path":    None,
        "error":       None,
    }

    # 5. Queue background task
    background_tasks.add_task(
        process_worksheet_job, job_id, student_id.strip(), topic.strip(),
        curriculum_id.strip() if curriculum_id else None, user_id,
    )

    return {"message": "Worksheet generation queued.", "job_id": job_id, "status": "Queued"}


@app.get("/api/v1/worksheet-pdf/{job_id}")
async def download_worksheet(job_id: str, request: Request):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")

    job = jobs[job_id]
    if job["status"] != "Completed" or not job.get("pdf_path"):
        raise HTTPException(status_code=409, detail="Worksheet not ready.")

    # Ownership check — only the tutor who generated it can download it
    token    = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_res = supabase_admin.auth.get_user(token)
    if not user_res or not user_res.user or user_res.user.id != job.get("user_id"):
        raise HTTPException(status_code=403, detail="Not authorised to access this file.")

    return FileResponse(
        job["pdf_path"],
        media_type="application/pdf",
        filename=os.path.basename(job["pdf_path"]),
    )


@app.post("/api/v1/webhooks/payhere")
async def payhere_webhook(request: Request):
    """
    PayHere POSTs here after every payment event.
    MUST return plain "OK" with 200 — PayHere retries if it doesn't get this.
    """
    form_data = await request.form()
    data      = dict(form_data)

    merchant_id      = data.get("merchant_id")
    order_id         = data.get("order_id")
    payhere_amount   = data.get("payhere_amount")
    payhere_currency = data.get("payhere_currency")
    status_code      = data.get("status_code")
    md5sig           = data.get("md5sig")

    # 1. Verify signature — reject anything that doesn't match
    if not verify_payhere_notification(
        merchant_id, order_id, payhere_amount,
        payhere_currency, status_code, md5sig
    ):
        print(f"⚠️  Hash mismatch for order {order_id}")
        raise HTTPException(status_code=400, detail="Hash mismatch")

    # 2. Only act on successful payments (status 2)
    # 2=Success, 0=Pending, -1=Cancelled, -2=Failed, -3=Chargedback
    if status_code == "2":
        # order_id format: "CREDITS_<user_uuid>"
        parts = order_id.split("_", 1)   # split on first _ only
        if len(parts) == 2:
            user_id = parts[1]            # everything after first underscore = UUID
            profile = supabase_admin.table("profiles").select("credits").eq("id", user_id).single().execute()
            current = profile.data.get("credits", 0)
            supabase_admin.table("profiles").update({"credits": current + 100}).eq("id", user_id).execute()
            print(f"✅ +100 credits → user {user_id} (order {order_id})")
        else:
            print(f"⚠️  Could not parse user_id from order_id: {order_id}")
    else:
        print(f"ℹ️  Payment status {status_code} for order {order_id} — no action taken")

    # PayHere requires this exact plain text response
    return JSONResponse(content="OK")


@app.get("/api/v1/credits")
async def get_credits(request: Request):
    """Returns current credit balance for the authenticated user."""
    token    = request.headers.get("Authorization", "").replace("Bearer ", "")
    user_res = supabase_admin.auth.get_user(token)
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = user_res.user.id
    profile = supabase_admin.table("profiles").select("credits").eq("id", user_id).single().execute()
    return {"credits": profile.data.get("credits", 0)}