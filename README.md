# AI Exam Marking Pipeline v2

## Setup

```bash
pip install google-genai pymupdf pdf2image pydantic python-dotenv
```

Create a `.env` file:
```
GEMINI_API_KEY=your_key_here
```

---

## Usage

### 1. Run the full pipeline

```bash
python pipeline.py student_paper.pdf marking_scheme.pdf
```

Or from Python:
```python
from pipeline import run_pipeline
run_pipeline("student_paper.pdf", "marking_scheme.pdf")
```

### 2. Review flagged questions (teacher step)

```bash
python review_cli.py
```

### 3. Track student progress

```bash
python student_tracker.py
```

---

## How the iterative improvement works

```
Run pipeline → grading saved to eval_store.db
                    ↓
            Teacher runs review_cli.py
                    ↓
        Flags correct/incorrect + corrections
                    ↓
    Corrections stored as few-shot examples
                    ↓
    Next pipeline run pulls examples by topic
    and injects them into the grading prompt
                    ↓
            Accuracy improves over time
```

---

## Files

| File | Purpose |
|---|---|
| `pipeline.py` | Main pipeline (stages 1-4 + report) |
| `review_cli.py` | Teacher review interface |
| `student_tracker.py` | Student profiles + progress |
| `eval_store.db` | SQLite database (auto-created) |
| `isolated_questions/` | Per-question PDFs (auto-created) |
| `exam_report.json` | Latest run report (auto-created) |

---

## Architecture

```
Stage 1: Layout Segmentation    Gemini Vision → question→page map
Stage 2: PDF Slicing            PyMuPDF → one PDF per question
Stage 3a: Transcription         Gemini Vision → raw text only
Stage 3b: Grading               Gemini + mark scheme → structured grades
Stage 4: Eval Store             SQLite → reviewable, few-shot source
Stage 5: Report                 JSON + console summary
```
