"""
test_single_question.py
------------------------
Test transcription + grading on a single already-sliced question PDF.
Skips layout segmentation and PDF slicing entirely.

Usage:
    python test_single_question.py 14
    python test_single_question.py 14 --retranscribe
"""

import os
import sys
import json
from dotenv import load_dotenv
load_dotenv()

from google import genai
from pipeline import (
    init_db, transcribe_question, grade_question,
    get_few_shot_examples, save_grading_result,
    ParsedMarkScheme, DB_PATH
)

# ── Config ────────────────────────────────────────────────────────────
QUESTION_NUM   = int(sys.argv[1]) if len(sys.argv) > 1 else 14
QUESTION_PDF   = f"isolated_questions/question_{QUESTION_NUM}.pdf"
SCHEME_CACHE   = "IGCSE_Nov_2025_marking_scheme_parsed.json"
SAVE_TO_DB     = "--save" in sys.argv
# ─────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(QUESTION_PDF):
        print(f"❌ Not found: {QUESTION_PDF}")
        print(f"   Check your isolated_questions/ folder for available files:")
        for f in sorted(os.listdir("isolated_questions")):
            print(f"   {f}")
        sys.exit(1)

    if not os.path.exists(SCHEME_CACHE):
        print(f"❌ Scheme cache not found: {SCHEME_CACHE}")
        print(f"   Run the full pipeline once first to generate the cache.")
        sys.exit(1)

    init_db()
    client = genai.Client()

    # Load cached scheme — zero API calls
    with open(SCHEME_CACHE) as f:
        parsed_scheme = ParsedMarkScheme.model_validate_json(f.read())
    rubric_index = {q.question_number: q for q in parsed_scheme.questions}

    rubric = rubric_index.get(QUESTION_NUM)
    if not rubric:
        print(f"❌ No rubric found for Q{QUESTION_NUM} in cache.")
        print(f"   Available question numbers: {sorted(rubric_index.keys())}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Testing Q{QUESTION_NUM} — {rubric.total_marks} marks | {len(rubric.sub_parts)} sub-parts")
    print(f"  PDF: {QUESTION_PDF}")
    print(f"{'='*60}")

    # ── Pass A: Transcription ─────────────────────────────────────────
    print(f"\n[A] Transcribing handwriting...")
    transcription = transcribe_question(QUESTION_PDF, QUESTION_NUM, client)

    print(f"    Confidence       : {transcription.transcription_confidence:.0%}")
    print(f"    Contains diagrams: {transcription.contains_diagrams}")
    if transcription.illegible_regions:
        print(f"    Illegible regions: {transcription.illegible_regions}")
    print(f"\n    Transcription:\n    {'─'*50}")
    for line in transcription.raw_transcription.split("\n"):
        print(f"    {line}")

    # ── Pass B: Grading ───────────────────────────────────────────────
    print(f"\n[B] Grading against rubric...")
    few_shots = get_few_shot_examples(topic=rubric.general_notes, n=3)
    grading   = grade_question(transcription, rubric, client, few_shots)

    print(f"\n    Score      : {grading.total_score}/{grading.max_score}")
    print(f"    Confidence : {grading.overall_confidence:.0%}")
    print(f"    Topic      : {grading.topic_classification}")
    if grading.flag_for_human_review:
        print(f"    ⚠️  FLAGGED : {grading.review_reason}")

    print(f"\n    Sub-parts:")
    for sp in grading.sub_parts:
        mc = f" ← {sp.identified_misconception}" if sp.identified_misconception else ""
        print(f"      ({sp.part_identifier}) {sp.marks_awarded}/{sp.marks_possible}"
              f"  M:{sp.method_marks_earned} A:{sp.accuracy_marks_earned}{mc}")
        print(f"           {sp.detailed_critique[:120]}")

    print(f"\n    Feedback to student:")
    print(f"    {grading.pedagogical_remedial_strategy}")

    # ── Optionally save to DB ─────────────────────────────────────────
    if SAVE_TO_DB:
        eval_id = save_grading_result(
            parsed_scheme.paper_title, QUESTION_NUM,
            QUESTION_PDF, transcription, grading
        )
        print(f"\n    💾 Saved to eval store (ID: {eval_id})")
    else:
        print(f"\n    (Not saved to DB — pass --save to persist)")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()