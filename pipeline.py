"""
=============================================================================
  AI EXAM MARKING PIPELINE  —  Upgraded v2.2
=============================================================================
  Stages:
    0. Mark scheme pre-parse  (Gemini → ParsedMarkScheme JSON, ONE call)
    1. Layout segmentation    (Gemini multimodal → ExamPaperStructure)
    2. PDF slicing            (PyMuPDF → per-question PDFs)
    3a. Transcription pass    (Gemini Vision → raw handwriting text)
    3b. Grading pass          (Gemini text-only → AcademicEvaluationMatrix)
         ↑ sends rubric JSON (~500 tokens) not full PDF (~15,000 tokens)
    4. Eval store             (SQLite → reviewable, few-shot source)
    5. Report export          (JSON + pretty console summary)

  Token saving vs v2.1:
    Old: scheme PDF sent on every grading call  → ~15,000 tokens × N questions
    New: scheme parsed once, rubric text per Q  → ~500 tokens × N questions
    10-question paper: saves ~143,000 tokens (~$0.01, but scales with volume)
=============================================================================
"""

import os
import re
import json
import time
import sqlite3
import traceback
from pathlib import Path
from typing import List, Optional

import fitz                          # PyMuPDF
from pdf2image import convert_from_path
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

PROMPT_VERSION      = "v2.2"          # bump this whenever you change prompts
DB_PATH             = "eval_store.db"
LOW_CONF_THRESHOLD  = 0.65            # flag for human review below this


# ============================================================================
# SECTION 1 — PYDANTIC SCHEMAS
# ============================================================================

class QuestionMapping(BaseModel):
    question_number: int = Field(description="Main integer question number.")
    pages: List[int]     = Field(description="1-based page numbers this question spans.")

class ExamPaperStructure(BaseModel):
    paper_title: str
    mappings:    List[QuestionMapping]

# --- Transcription (Pass A) -------------------------------------------------

class TranscriptionResult(BaseModel):
    question_number:    int
    raw_transcription:  str  = Field(
        description="Verbatim transcription of ALL handwritten content including "
                    "crossed-out work, diagrams described in words, and every "
                    "calculation step visible on the page.")
    illegible_regions:  List[str] = Field(
        default_factory=list,
        description="List of regions where handwriting was too unclear to read. "
                    "E.g. ['line 3 of working', 'final answer box']")
    contains_diagrams:  bool = Field(
        description="True if the student drew any graphs, geometric shapes, or diagrams.")
    transcription_confidence: float = Field(
        description="Self-assessed confidence in transcription accuracy. 0.0–1.0.")

# --- Grading (Pass B) -------------------------------------------------------

class SubPartGrade(BaseModel):
    part_identifier:          str
    marks_awarded:            int
    marks_possible:           int
    method_marks_earned:      int
    accuracy_marks_earned:    int
    identified_misconception: Optional[str] = None
    detailed_critique:        str
    confidence:               float = Field(
        description="Confidence in this sub-part grading. 0.0–1.0.")
    ambiguous_aspects:        List[str] = Field(
        default_factory=list,
        description="Specific things that were unclear when awarding this mark.")

class AcademicEvaluationMatrix(BaseModel):
    question_number:               int
    total_score:                   int
    max_score:                     int
    topic_classification:          str
    sub_parts:                     List[SubPartGrade]
    pedagogical_remedial_strategy: str
    overall_confidence:            float = Field(
        description="Overall grading confidence 0.0–1.0. "
                    "Low if handwriting was unclear or answer was ambiguous.")
    flag_for_human_review:         bool  = Field(
        description="True if confidence is low or there is genuine ambiguity "
                    "a human examiner should resolve.")
    review_reason:                 Optional[str] = Field(
        default=None,
        description="If flagged, explain exactly what is ambiguous.")


# --- Mark Scheme Pre-parse (one-time) ---------------------------------------

class SubPartRubric(BaseModel):
    part_identifier:          str   = Field(description="e.g. 'a', 'b(i)', 'c'")
    marks:                    int
    method_mark_criteria:     str   = Field(description="What the student must show to earn M marks.")
    accuracy_mark_criteria:   str   = Field(description="What the student must show to earn A marks.")
    acceptable_alternatives:  List[str] = Field(default_factory=list)
    common_errors:            List[str] = Field(default_factory=list)

class QuestionRubric(BaseModel):
    question_number: int
    total_marks:     int
    sub_parts:       List[SubPartRubric]
    general_notes:   str = Field(default="", description="Any general examiner notes for this question.")

class ParsedMarkScheme(BaseModel):
    paper_title: str
    subject:     str
    questions:   List[QuestionRubric]


# ============================================================================
# SECTION 2 — EVAL STORE  (SQLite — your 'trainable skill' database)
# ============================================================================

def init_db(db_path: str = DB_PATH):
    """Create tables if they don't exist, and migrate existing DBs."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS grading_evals (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_title           TEXT,
            question_number       INTEGER,
            question_pdf_path     TEXT,
            transcription         TEXT,
            ai_grading            TEXT,
            teacher_correction    TEXT,
            is_reviewed           BOOLEAN DEFAULT FALSE,
            is_correct            BOOLEAN,
            prompt_version        TEXT,
            topic_classification  TEXT,
            total_score           INTEGER,
            max_score             INTEGER,
            overall_confidence    REAL,
            flag_for_human_review BOOLEAN,
            review_reason         TEXT,
            created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS students (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            school     TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS attempts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id    INTEGER REFERENCES students(id),
            paper_title   TEXT,
            subject       TEXT,
            attempt_date  DATE DEFAULT CURRENT_DATE,
            total_marks   INTEGER,
            marks_awarded INTEGER,
            percentage    REAL,
            report_json   TEXT
        );
    """)

    # ── Migrations: safely add columns that may be missing in older DBs ──
    existing_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(grading_evals)").fetchall()
    }
    migrations = {
        "review_reason":         "ALTER TABLE grading_evals ADD COLUMN review_reason TEXT",
        "flag_for_human_review": "ALTER TABLE grading_evals ADD COLUMN flag_for_human_review BOOLEAN",
        "overall_confidence":    "ALTER TABLE grading_evals ADD COLUMN overall_confidence REAL",
        "topic_classification":  "ALTER TABLE grading_evals ADD COLUMN topic_classification TEXT",
    }
    for col, sql in migrations.items():
        if col not in existing_cols:
            print(f"  🔧 DB migration: adding column '{col}'")
            conn.execute(sql)

    conn.commit()
    conn.close()


def save_grading_result(
    paper_title:    str,
    q_num:          int,
    q_pdf_path:     str,
    transcription:  TranscriptionResult,
    grading:        AcademicEvaluationMatrix,
    db_path:        str = DB_PATH,
) -> int:
    """Persist one question's results. Returns the row ID."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("""
        INSERT INTO grading_evals
            (paper_title, question_number, question_pdf_path,
             transcription, ai_grading, prompt_version,
             topic_classification, total_score, max_score,
             overall_confidence, flag_for_human_review)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        paper_title,
        q_num,
        q_pdf_path,
        transcription.model_dump_json(),
        grading.model_dump_json(),
        PROMPT_VERSION,
        grading.topic_classification,
        grading.total_score,
        grading.max_score,
        grading.overall_confidence,
        grading.flag_for_human_review,
    ))
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_few_shot_examples(topic: str, n: int = 3, db_path: str = DB_PATH) -> List[dict]:
    """
    Pull teacher-reviewed correct examples for a topic.
    These are injected into the grading prompt to improve accuracy over time.
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT transcription, ai_grading, teacher_correction
        FROM   grading_evals
        WHERE  is_reviewed = TRUE
          AND  is_correct  = TRUE
          AND  topic_classification = ?
        ORDER  BY created_at DESC
        LIMIT  ?
    """, (topic, n)).fetchall()
    conn.close()

    examples = []
    for transcription_json, grading_json, correction_json in rows:
        examples.append({
            "transcription": json.loads(transcription_json),
            "grading":       json.loads(grading_json),
            "correction":    json.loads(correction_json) if correction_json else None,
        })
    return examples


def get_review_queue(db_path: str = DB_PATH) -> List[dict]:
    """Return all unreviewed flagged cases for teacher attention."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT id, paper_title, question_number, overall_confidence,
               review_reason, ai_grading
        FROM   grading_evals
        WHERE  flag_for_human_review = TRUE
          AND  is_reviewed           = FALSE
        ORDER  BY created_at DESC
    """).fetchall()
    conn.close()
    return [
        {
            "id":              r[0],
            "paper_title":     r[1],
            "question_number": r[2],
            "confidence":      r[3],
            "review_reason":   r[4],
            "grading":         json.loads(r[5]),
        }
        for r in rows
    ]


def submit_teacher_review(
    eval_id:            int,
    is_correct:         bool,
    teacher_correction: Optional[dict] = None,
    db_path:            str = DB_PATH,
):
    """
    Teacher calls this after inspecting a flagged result.
    Corrected gradings feed back into the few-shot pool automatically.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("""
        UPDATE grading_evals
        SET    is_reviewed        = TRUE,
               is_correct         = ?,
               teacher_correction = ?
        WHERE  id = ?
    """, (is_correct, json.dumps(teacher_correction) if teacher_correction else None, eval_id))
    conn.commit()
    conn.close()
    print(f"✅ Review saved for eval ID {eval_id}. is_correct={is_correct}")


# ============================================================================
# SECTION 3 — RETRY HELPER  (replaces hard sleep)
# ============================================================================

def call_with_retry(fn, retries: int = 6, base_delay: float = 30.0):
    """
    Exponential backoff retry wrapper.
    For 429s, honours the retryDelay suggested by the API if present.
    """
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit   = "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str or "overloaded" in err_str
            is_server_error = "500" in err_str or "503" in err_str or "unavailable" in err_str

            if attempt == retries - 1:
                raise

            if is_rate_limit or is_server_error:
                # Try to extract the suggested retry delay from the error message
                suggested = None
                import re as _re
                match = _re.search(r"retry[^\d]*(\d+)[\.\d]*s", str(e), _re.IGNORECASE)
                if match:
                    suggested = int(match.group(1)) + 5  # add 5s buffer

                wait = suggested if suggested else base_delay * (2 ** attempt)
                print(f"  ⏳ Retry {attempt+1}/{retries} — waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


# ============================================================================
# SECTION 4 — STAGE 0: MARK SCHEME PRE-PARSING  (one call, saves ~5x tokens)
# ============================================================================

def parse_marking_scheme(
    scheme_pdf: str,
    client:     genai.Client,
) -> tuple:
    """
    ONE-TIME call at pipeline start.
    Converts the full marking scheme PDF into a structured ParsedMarkScheme.
    Falls back to chunked parsing (by question range) if the full PDF is too
    large for a single response.
    """
    print("\n📑 STAGE 0 — Mark Scheme Pre-parsing")
    print("  Uploading scheme PDF (one-time)...")
    scheme_blob = client.files.upload(file=scheme_pdf, config={"mime_type": "application/pdf"})

    def _parse_range(q_from: int, q_to: int):
        """Ask Gemini to parse only questions q_from..q_to from the scheme."""
        range_str = f"questions {q_from} to {q_to}" if q_to else f"question {q_from} onwards"
        prompt = f"""
        You are parsing an official IGCSE / GCSE mathematics marking scheme.
        Parse ONLY {range_str} from this document.

        For each question and sub-part include:
        - The exact mark allocation (M marks and A marks separately where stated)
        - The exact acceptable answer(s) including alternative forms
        - Any "follow through" (ft) or "own figure" (of) rules
        - Common errors or misconceptions noted by the examiner
        - Any special marking instructions (e.g. "accept equivalent fractions")

        Be thorough and literal — do not paraphrase the mark scheme criteria.
        Set paper_title and subject from the document header.
        """

        def _call():
            return client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[scheme_blob, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ParsedMarkScheme,
                    temperature=0.0,
                    max_output_tokens=16384,
                ),
            )
        return call_with_retry(_call)

    # ── Attempt 1: Parse the full scheme in one shot ──────────────────────
    prompt_full = """
    You are parsing an official IGCSE / GCSE mathematics marking scheme.

    Extract EVERY question's marking criteria into the structured JSON format.
    For each question and sub-part include:
    - The exact mark allocation (M marks and A marks separately where stated)
    - The exact acceptable answer(s) including alternative forms
    - Any "follow through" (ft) or "own figure" (of) rules
    - Common errors or misconceptions noted by the examiner
    - Any special marking instructions (e.g. "accept equivalent fractions")

    Be thorough and literal — do not paraphrase the mark scheme criteria.
    A grading AI will rely on this JSON as its sole source of truth.
    """

    def _call_full():
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[scheme_blob, prompt_full],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ParsedMarkScheme,
                temperature=0.0,
                max_output_tokens=16384,
            ),
        )

    response = call_with_retry(_call_full)
    finish_reason = getattr(response.candidates[0], "finish_reason", "unknown") if response.candidates else "unknown"
    print(f"  Response: {len(response.text)} chars | Finish reason: {finish_reason}")

    truncated = finish_reason not in ("STOP", "stop", 1)

    if not truncated:
        try:
            parsed_scheme = ParsedMarkScheme.model_validate_json(response.text)
            print(f"  ✅ Full parse succeeded — {len(parsed_scheme.questions)} questions extracted.")
            try:
                client.files.delete(name=scheme_blob.name)
            except Exception:
                pass
            rubric_index = {q.question_number: q for q in parsed_scheme.questions}
            return parsed_scheme, rubric_index
        except Exception as e:
            print(f"  ⚠️  Full parse validation failed: {e}")
            print(f"  → Falling back to chunked parsing...")
    else:
        print(f"  ⚠️  Response truncated (finish_reason={finish_reason}) → falling back to chunked parsing...")

    # ── Attempt 2: Chunked parsing — 5 questions at a time ───────────────
    print("  Chunked mode: parsing 5 questions per call...")
    all_rubrics   = []
    paper_title   = "Unknown Paper"
    subject       = "Mathematics"
    chunk_size    = 5
    q_start       = 1

    while True:
        q_end = q_start + chunk_size - 1
        print(f"    Parsing Q{q_start}–{q_end}...")

        try:
            chunk_response = _parse_range(q_start, q_end)
            chunk = ParsedMarkScheme.model_validate_json(chunk_response.text)

            if not chunk.questions:
                print(f"    No questions found in Q{q_start}–{q_end} — assuming end of paper.")
                break

            all_rubrics.extend(chunk.questions)
            paper_title = chunk.paper_title or paper_title
            subject     = chunk.subject     or subject
            q_start     = q_end + 1

        except Exception as e:
            print(f"    ⚠️  Chunk Q{q_start}–{q_end} failed: {e} — stopping here.")
            break

    try:
        client.files.delete(name=scheme_blob.name)
    except Exception:
        pass

    if not all_rubrics:
        raise RuntimeError("Mark scheme parsing failed — no rubrics extracted. Check the PDF.")

    parsed_scheme = ParsedMarkScheme(
        paper_title=paper_title,
        subject=subject,
        questions=all_rubrics,
    )

    print(f"  ✅ Chunked parse complete — {len(parsed_scheme.questions)} questions extracted.")
    rubric_index = {q.question_number: q for q in parsed_scheme.questions}
    return parsed_scheme, rubric_index


# ============================================================================
# SECTION 5 — STAGE 1: LAYOUT SEGMENTATION
# ============================================================================

def execute_ai_layout_segmentation(
    pdf_path: str,
    client:   genai.Client,
) -> ExamPaperStructure:
    """
    Converts PDF pages to low-res images, asks Gemini to map
    question → page assignments, returns structured blueprint.
    """
    print("\n📄 STAGE 1 — Layout Segmentation")
    print("  Converting pages to images (70 DPI for layout scan)...")
    images     = convert_from_path(pdf_path, dpi=70)
    temp_files = []

    for idx, img in enumerate(images):
        path = f"_tmp_layout_page_{idx+1}.jpg"
        img.save(path, "JPEG")
        temp_files.append(path)

    print(f"  Uploading {len(temp_files)} page(s) to Gemini Files API...")
    uploaded = [client.files.upload(file=p, config={"mime_type": "image/jpeg"}) for p in temp_files]

    prompt = """
    Analyze these pages of a scanned student mathematics exam answer booklet.
    
    For every distinct main question number (1, 2, 3 ...) visible, record:
    - The integer question number
    - Every 1-based page number where that question's answer workspace appears
    
    Rules:
    - If a question spans multiple pages, list all of them.
    - Ignore sub-parts (a, b, c) — only track main question numbers.
    - If a page contains two questions, list that page under BOTH questions.
    - Ignore any printed question text pages — only pages with student handwriting.
    - Be robust to faint printing, messy handwriting, and poor scan quality.
    """

    def _call():
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[*uploaded, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExamPaperStructure,
                temperature=0.1,
                max_output_tokens=8192,
            ),
        )

    response = call_with_retry(_call)

    finish_reason = (
        getattr(response.candidates[0], "finish_reason", "unknown")
        if response.candidates else "unknown"
    )
    truncated = finish_reason not in ("STOP", "stop", 1)

    if not truncated:
        try:
            blueprint = ExamPaperStructure.model_validate_json(response.text)
        except Exception as e:
            print(f"  ⚠️  Layout JSON invalid ({e}) — trying chunked fallback...")
            truncated = True

    if truncated:
        print(f"  ⚠️  Layout truncated — processing pages in chunks of 10...")
        all_mappings = []
        paper_title  = "Unknown Paper"
        chunk_size   = 10

        for chunk_start in range(0, len(uploaded), chunk_size):
            chunk_end    = min(chunk_start + chunk_size, len(uploaded))
            chunk_blobs  = uploaded[chunk_start:chunk_end]
            page_offset  = chunk_start  # pages in this chunk are offset by this

            print(f"    Processing pages {chunk_start+1}–{chunk_end}...")

            chunk_prompt = f"""
            Analyze these scanned exam booklet pages (they are pages {chunk_start+1} to {chunk_end} of the full booklet).
            For every distinct main question number visible, record:
            - The integer question number
            - Every 1-based page number (relative to the FULL booklet, so add {chunk_start} to any local page numbers)
            Rules:
            - Ignore sub-parts (a, b, c) — only main question numbers.
            - If a page has two questions, list it under both.
            - Only pages with student handwriting, not printed question pages.
            """

            def _chunk_call(blobs=chunk_blobs, p=chunk_prompt):
                return client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[*blobs, p],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ExamPaperStructure,
                        temperature=0.1,
                        max_output_tokens=4096,
                    ),
                )

            try:
                chunk_response = call_with_retry(_chunk_call)
                chunk_structure = ExamPaperStructure.model_validate_json(chunk_response.text)
                all_mappings.extend(chunk_structure.mappings)
                paper_title = chunk_structure.paper_title or paper_title
            except Exception as e:
                print(f"    ⚠️  Chunk pages {chunk_start+1}–{chunk_end} failed: {e} — skipping.")

        if not all_mappings:
            raise RuntimeError("Layout segmentation failed completely — no question mappings found.")

        # Merge duplicate question numbers (same Q appearing in multiple chunks)
        merged = {}
        for m in all_mappings:
            if m.question_number in merged:
                merged[m.question_number].pages = sorted(
                    set(merged[m.question_number].pages + m.pages)
                )
            else:
                merged[m.question_number] = m

        blueprint = ExamPaperStructure(
            paper_title=paper_title,
            mappings=sorted(merged.values(), key=lambda x: x.question_number),
        )

    # cleanup temp files
    for p in temp_files:
        if os.path.exists(p):
            os.remove(p)
    for blob in uploaded:
        try:
            client.files.delete(name=blob.name)
        except Exception:
            pass

    print(f"  ✅ Blueprint decoded — {len(blueprint.mappings)} questions found.")
    print(f"     Paper title: '{blueprint.paper_title}'")
    return blueprint


# ============================================================================
# SECTION 6 — STAGE 2: PDF SLICING
# ============================================================================

def segment_pdf_by_blueprint(
    pdf_path:   str,
    blueprint:  ExamPaperStructure,
    output_dir: str,
) -> List[str]:
    """
    Slices the source PDF into one PDF per question using the blueprint.
    Returns list of output file paths.
    """
    print("\n✂️  STAGE 2 — PDF Slicing")
    os.makedirs(output_dir, exist_ok=True)
    source_doc = fitz.open(pdf_path)
    output_paths = []

    for mapping in blueprint.mappings:
        q_num  = mapping.question_number
        pages  = mapping.pages

        if not pages:
            print(f"  ⚠️  Q{q_num}: No pages in blueprint — skipping.")
            continue

        split_doc   = fitz.open()
        pages_added = 0

        for page_num in pages:
            zero_idx = page_num - 1
            if 0 <= zero_idx < len(source_doc):
                split_doc.insert_pdf(source_doc, from_page=zero_idx, to_page=zero_idx)
                pages_added += 1
            else:
                print(f"  ⚠️  Q{q_num}: Page {page_num} out of range — skipped.")

        if pages_added == 0:
            print(f"  ⚠️  Q{q_num}: No valid pages extracted — skipping.")
            split_doc.close()
            continue

        out_path = os.path.join(output_dir, f"question_{q_num}.pdf")
        split_doc.save(out_path)
        split_doc.close()
        output_paths.append(out_path)
        print(f"  💾 Q{q_num}: Saved ({pages_added} page(s)) → {out_path}")

    source_doc.close()
    print(f"  ✅ Sliced into {len(output_paths)} question PDF(s).")
    return output_paths


# ============================================================================
# SECTION 7 — STAGE 3A: TRANSCRIPTION PASS
# ============================================================================

def transcribe_question(
    student_pdf_path: str,
    question_number:  int,
    client:           genai.Client,
) -> TranscriptionResult:
    """
    PASS A — Transcription only.
    Reads the handwritten PDF and returns a faithful text transcription.
    No grading logic here — clean separation of concerns.
    """
    student_blob = client.files.upload(file=student_pdf_path, config={"mime_type": "application/pdf"})

    prompt = f"""
    You are a specialist in reading handwritten student mathematics exam scripts.
    Your task is TRANSCRIPTION. While you should not grade the script, you must use 
    mathematical logic and context to resolve ambiguous handwriting.

    Rules for Ambiguous Characters:
    - If a character is poorly formed (e.g., looks like a '?' or a random symbol), do not 
      just transcribe it literally if surrounding context makes its identity clear.
    - Analyze the equation: If a student writes "2x + [unclear] = 7" and the next line is "2x = 4", 
      deduce that the unclear character is a 3. 
    - Act like a human examiner: cross-reference the final answer box and previous steps to resolve messy digits.
    
    Transcribe ALL handwritten content on these page(s) for Question {question_number}:
    - Every line of working, even if crossed out (note it as "[CROSSED OUT: ...]")
    - Every numerical calculation and algebraic step
    - Any diagrams (describe them as "[DIAGRAM: ...]")
    - The final answer, clearly marked as "[FINAL ANSWER: ...]"
    - Any margin notes or annotations
 
    For regions you cannot read clearly EVEN AFTER using context to resolve ambiguity,
    write "[ILLEGIBLE: description of region]" and list those regions in illegible_regions.
 
    Be precise and literal. Your transcription will be used by another system to grade.
    """

    def _call():
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[student_blob, prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TranscriptionResult,
                temperature=0.0,
                max_output_tokens=4096,
            ),
        )

    response = call_with_retry(_call)

    # Check finish reason — truncated JSON fails Pydantic validation
    finish_reason = (
        getattr(response.candidates[0], "finish_reason", "unknown")
        if response.candidates else "unknown"
    )
    truncated = finish_reason not in ("STOP", "stop", 1)

    if not truncated:
        try:
            result = TranscriptionResult.model_validate_json(response.text)
            try:
                client.files.delete(name=student_blob.name)
            except Exception:
                pass
            return result
        except Exception as e:
            print(f"      ⚠️  Structured transcription failed ({e}) — trying plain text fallback...")
            truncated = True  # fall through to fallback

    if truncated:
        print(f"      ⚠️  Transcription truncated or invalid — using plain text fallback...")

        fallback_prompt = f"""
        Transcribe the handwritten mathematics working for Question {question_number}.
        
        Rules:
        - Write each step on its own line
        - Use plain text for maths, e.g. "x^2 + 3x - 2 = 0"
        - Mark crossed out work as [CROSSED OUT: ...]
        - Mark the final answer as FINAL ANSWER: ...
        - If something is unreadable write [ILLEGIBLE]
        - Be concise — do not explain or interpret, just transcribe
        - Maximum 400 words
        """

        def _fallback():
            return client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[student_blob, fallback_prompt],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=2048,
                ),
            )

        fallback_response = call_with_retry(_fallback)

        try:
            client.files.delete(name=student_blob.name)
        except Exception:
            pass

        return TranscriptionResult(
            question_number=question_number,
            raw_transcription=fallback_response.text.strip(),
            illegible_regions=["⚠️ Fallback mode — structured transcription was truncated"],
            contains_diagrams=False,
            transcription_confidence=0.75,
        )


# ============================================================================
# SECTION 8 — STAGE 3B: GRADING PASS
# ============================================================================

def grade_question(
    transcription:     TranscriptionResult,
    question_rubric:   QuestionRubric,      # pre-parsed rubric — text only, no blob
    client:            genai.Client,
    few_shot_examples: List[dict] = None,
) -> AcademicEvaluationMatrix:
    """
    PASS B — Grading only.
    Works from the transcription text + the pre-parsed rubric for this question.
    No PDF blob is sent — the rubric is plain JSON text (~500 tokens vs ~15,000).
    Injects few-shot examples if available.
    """
    few_shot_examples = few_shot_examples or []

    # Build few-shot block from teacher-reviewed examples
    examples_block = ""
    if few_shot_examples:
        examples_block = "\n\n--- REVIEWED EXAMPLES (use these to calibrate your judgement) ---\n"
        for i, ex in enumerate(few_shot_examples, 1):
            examples_block += f"""
EXAMPLE {i}:
Student transcription: {ex['transcription'].get('raw_transcription', '')}
Correct grading: {json.dumps(ex['correction'] or ex['grading'], indent=2)}
---"""

    system_instruction = """
    You are a Chief Assistant Principal Examiner for International GCSE Mathematics.
    CRITICAL MANDATE: You must grade STRICTLY against the provided OFFICIAL MARK SCHEME. 
    Do not invent your own criteria. If a student's final answer matches an acceptable alternative 
    in the rubric and their working follows a logically valid path towards it, you MUST award the marks. 
    Never penalize a student for using an alternative mathematical layout if it is mathematically correct 
    and achieves a rubric-approved result.
    """

    rubric_text = json.dumps(question_rubric.model_dump(), indent=2)

    prompt = f"""
    {examples_block}

    OFFICIAL MARK SCHEME FOR QUESTION {question_rubric.question_number}:
    {rubric_text}

    STUDENT'S TRANSCRIBED ANSWER:
    {transcription.raw_transcription}

    ILLEGIBLE REGIONS (treat these carefully):
    {', '.join(transcription.illegible_regions) if transcription.illegible_regions else 'None'}

    TRANSCRIPTION CONFIDENCE: {transcription.transcription_confidence:.0%}

    INSTRUCTIONS:
    1. Use the rubric above — it is the complete marking criteria for this question.
    2. For each sub-part, determine which M (method) and A (accuracy) marks are earned.
    3. If a region was illegible, state this and consider whether benefit of the doubt applies.
    4. Set overall_confidence based on how certain you are. If the transcription had
       illegible regions or the answer is borderline, lower your confidence and set
       flag_for_human_review = True with a clear review_reason.
    5. Write pedagogical_remedial_strategy directly to the student, in plain English.
    """

    def _call():
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[prompt],
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=AcademicEvaluationMatrix,
                temperature=0.0,
                max_output_tokens=8192,
            ),
        )

    response = call_with_retry(_call)

    finish_reason = (
        getattr(response.candidates[0], "finish_reason", "unknown")
        if response.candidates else "unknown"
    )
    truncated = finish_reason not in ("STOP", "stop", 1)

    if not truncated:
        try:
            grading = AcademicEvaluationMatrix.model_validate_json(response.text)
        except Exception as e:
            print(f"      ⚠️  Grading JSON invalid ({e}) — trying simplified fallback...")
            truncated = True

    if truncated:
        print(f"      ⚠️  Grading truncated or invalid — using simplified fallback...")

        fallback_prompt = f"""
        Grade Question {question_rubric.question_number} using this rubric:
        {json.dumps(question_rubric.model_dump())}

        Student's answer:
        {transcription.raw_transcription[:1500]}
        
        Keep text fields extremely short (under 50 chars). 
        Do not use special characters.
        """

        def _fallback():
            return client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[fallback_prompt],
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=AcademicEvaluationMatrix,
                    temperature=0.0,
                    max_output_tokens=6000,
                ),
            )

        fallback_response = call_with_retry(_fallback)
        
        try:
            grading = AcademicEvaluationMatrix.model_validate_json(fallback_response.text)
            grading.flag_for_human_review = True
            grading.review_reason = "⚠️ Fallback grading used — verify manually."
        except Exception as e:
            print(f"      🚨 Critical Fallback Failure ({e}) — injecting blank review matrix.")
            # Hardcoded safety net prevents the entire script from crashing
            grading = AcademicEvaluationMatrix(
                question_number=question_rubric.question_number,
                total_score=0,
                max_score=question_rubric.total_marks,
                topic_classification="Unknown",
                sub_parts=[],
                pedagogical_remedial_strategy="AI grading failed due to complexity. Manual review required.",
                overall_confidence=0.0,
                flag_for_human_review=True,
                review_reason="CRITICAL: All structured parsing failed due to token limits."
            )

    # Auto-flag if confidence is below threshold
    if grading.overall_confidence < LOW_CONF_THRESHOLD and not grading.flag_for_human_review:
        grading.flag_for_human_review = True
        grading.review_reason = (
            f"Auto-flagged: confidence {grading.overall_confidence:.0%} "
            f"below threshold {LOW_CONF_THRESHOLD:.0%}"
        )

    return grading


# ============================================================================
# SECTION 8 — REPORT GENERATION
# ============================================================================

def extract_question_number_from_path(path: str) -> int:
    """Extract integer question number from filename like 'question_3.pdf'."""
    match = re.search(r"question_(\d+)", os.path.basename(path))
    return int(match.group(1)) if match else 0


def generate_report(
    paper_title:  str,
    results:      List[dict],
    output_path:  str = "exam_report.json",
) -> dict:
    """Build final JSON report and save it."""
    total_awarded  = sum(r["grading"]["total_score"] for r in results)
    total_possible = sum(r["grading"]["max_score"]   for r in results)
    percentage     = (total_awarded / total_possible * 100) if total_possible else 0

    report = {
        "paper_title":     paper_title,
        "prompt_version":  PROMPT_VERSION,
        "summary": {
            "total_marks_awarded":  total_awarded,
            "total_marks_possible": total_possible,
            "percentage":           round(percentage, 1),
            "questions_flagged":    sum(
                1 for r in results if r["grading"]["flag_for_human_review"]
            ),
        },
        "questions": results,
    }

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    return report


def print_report_summary(report: dict):
    """Pretty console output."""
    s = report["summary"]
    print("\n" + "=" * 65)
    print(f"  EXAM REPORT — {report['paper_title']}")
    print(f"  Prompt version: {report['prompt_version']}")
    print("=" * 65)
    print(f"  Total Score  : {s['total_marks_awarded']} / {s['total_marks_possible']}"
          f"  ({s['percentage']}%)")
    print(f"  Flagged      : {s['questions_flagged']} question(s) need human review")
    print("-" * 65)

    for r in report["questions"]:
        g    = r["grading"]
        flag = " ⚠️  REVIEW NEEDED" if g["flag_for_human_review"] else ""
        print(f"\n  Q{g['question_number']:>2}  {g['total_score']}/{g['max_score']}"
              f"  [{g['topic_classification']}]"
              f"  conf={g['overall_confidence']:.0%}{flag}")
        if g["flag_for_human_review"] and g.get("review_reason"):
            print(f"       Reason: {g['review_reason']}")
        for sp in g["sub_parts"]:
            mc = f" ← {sp['identified_misconception']}" if sp["identified_misconception"] else ""
            print(f"       ({sp['part_identifier']}) {sp['marks_awarded']}/{sp['marks_possible']}{mc}")
        print(f"       Advice: {g['pedagogical_remedial_strategy'][:120]}...")

    print("\n" + "=" * 65)


# ============================================================================
# SECTION 9 — MAIN PIPELINE
# ============================================================================

def run_pipeline(
    student_pdf:    str,
    scheme_pdf:     str,
    output_dir:     str = "isolated_questions",
    report_path:    str = "exam_report.json",
    paper_title:    str = None,
):
    """
    Full end-to-end pipeline.
    Returns the final report dict.

    Token-efficient flow:
      Stage 0: Parse scheme PDF once → structured JSON rubrics
      Stage 1: Layout segmentation (low-res images)
      Stage 2: PDF slicing
      Stage 3a: Transcription per question (student PDF image)
      Stage 3b: Grading per question (text only — no PDF blob)
    """
    init_db()

    if not os.path.exists(student_pdf):
        raise FileNotFoundError(f"Student PDF not found: {student_pdf}")
    if not os.path.exists(scheme_pdf):
        raise FileNotFoundError(f"Marking scheme not found: {scheme_pdf}")

    client = genai.Client()

    # ── Stage 0: Parse marking scheme ONCE into structured JSON ──────────
    # ── Stage 0: Parse marking scheme (cached) ───────────────────────────
    scheme_cache_path = scheme_pdf.replace(".pdf", "_parsed.json")

    if os.path.exists(scheme_cache_path):
        print(f"\n📑 STAGE 0 — Mark Scheme Pre-parsing")
        print(f"  ✅ Cache found — loading from {scheme_cache_path} (delete to re-parse)")
        with open(scheme_cache_path) as f:
            parsed_scheme = ParsedMarkScheme.model_validate_json(f.read())
        rubric_index = {q.question_number: q for q in parsed_scheme.questions}
        print(f"     {len(parsed_scheme.questions)} question rubrics loaded.")
    else:
        parsed_scheme, rubric_index = parse_marking_scheme(scheme_pdf, client)
        # Save cache next to the scheme PDF
        with open(scheme_cache_path, "w") as f:
            f.write(parsed_scheme.model_dump_json(indent=2))
        print(f"  💾 Cached to {scheme_cache_path}")

    paper_title = paper_title or parsed_scheme.paper_title

    # ── Stage 1: Layout segmentation ─────────────────────────────────────
    blueprint   = execute_ai_layout_segmentation(student_pdf, client)
    paper_title = paper_title or blueprint.paper_title

    # ── Stage 2: PDF slicing ──────────────────────────────────────────────
    question_files = segment_pdf_by_blueprint(student_pdf, blueprint, output_dir)

    if not question_files:
        raise RuntimeError("No question files were produced — check the PDF.")

    all_results = []

    print(f"\n🔬 STAGE 3 — Transcription + Grading ({len(question_files)} questions)")
    print(f"   (Scheme pre-parsed — sending rubric text per question, not full PDF)")

    for q_path in question_files:
        q_num = extract_question_number_from_path(q_path)
        if q_num == 0:
            print(f"  ⚠️  Could not parse question number from {q_path} — skipping.")
            continue

        # Look up this question's rubric from the pre-parsed index
        rubric = rubric_index.get(q_num)
        if rubric is None:
            print(f"  ⚠️  Q{q_num}: No rubric found in parsed scheme — skipping.")
            continue

        print(f"\n  ── Question {q_num} ──────────────────────────────────────")

        try:
            # Pass A: Transcription (sends student image PDF)
            print(f"  [A] Transcribing handwriting...")
            transcription = transcribe_question(q_path, q_num, client)
            print(f"      Confidence: {transcription.transcription_confidence:.0%}"
                  + (f" | Illegible: {len(transcription.illegible_regions)} region(s)"
                     if transcription.illegible_regions else ""))

            # Fetch few-shot examples for this topic from eval store
            # (empty on first run; grows richer as teacher reviews accumulate)
            few_shots = get_few_shot_examples(topic=rubric.question_number, n=3)

            # Pass B: Grading (sends rubric text only — ~500 tokens instead of ~15,000)
            print(f"  [B] Grading against rubric (text-only, ~500 tokens)...")
            grading = grade_question(transcription, rubric, client, few_shots)
            print(f"      Score: {grading.total_score}/{grading.max_score}"
                  f" | Confidence: {grading.overall_confidence:.0%}"
                  + (" | ⚠️  FLAGGED" if grading.flag_for_human_review else ""))

            # Save to eval store
            eval_id = save_grading_result(
                paper_title, q_num, q_path, transcription, grading
            )
            print(f"      Saved to eval store (ID: {eval_id})")

            time.sleep(5)

            all_results.append({
                "eval_store_id":  eval_id,
                "question_pdf":   q_path,
                "transcription":  transcription.model_dump(),
                "grading":        grading.model_dump(),
            })

        except Exception as e:
            print(f"  ❌ Q{q_num} failed: {e}")
            traceback.print_exc()

    # ── Stage 4: Report ───────────────────────────────────────────────────
    report = generate_report(paper_title, all_results, report_path)
    print_report_summary(report)
    print(f"\n📁 Full report saved → {report_path}")

    # Print review queue
    queue = get_review_queue()
    if queue:
        print(f"\n⚠️  {len(queue)} question(s) in the human review queue.")
        print("   Run `review_cli.py` to process them.")

    return report


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import sys

    # Defaults — override via CLI args or edit here
    STUDENT_PDF = sys.argv[1] if len(sys.argv) > 1 else "student_paper.pdf"
    SCHEME_PDF  = sys.argv[2] if len(sys.argv) > 2 else "marking_scheme.pdf"

    if "GEMINI_API_KEY" not in os.environ:
        print("❌ Missing GEMINI_API_KEY in environment. Add it to your .env file.")
        sys.exit(1)

    run_pipeline(
        student_pdf = STUDENT_PDF,
        scheme_pdf  = SCHEME_PDF,
        output_dir  = "isolated_questions",
        report_path = "exam_report.json",
    )