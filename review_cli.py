"""
=============================================================================
  TEACHER REVIEW CLI  —  review_cli.py  (v3)
=============================================================================
  Lets you review graded questions with structured error categorisation.
  Corrections (including WHY the AI was wrong) are stored and fed back as
  few-shot examples — including their error_analysis — into future grading.

  Usage:
      python review_cli.py                  # review all unreviewed
      python review_cli.py --flagged-only   # only items flagged for review
      python review_cli.py --fallback-only  # only items where a fallback fired
      python review_cli.py --all            # re-review everything
=============================================================================
"""

import json
import sys
import sqlite3
from pipeline import submit_teacher_review, DB_PATH, init_db

# ── Error taxonomy ──────────────────────────────────────────────────────────

TRANSCRIPTION_ERRORS = {
    "1": "Digit misread (e.g. 3→9, 7→1)",
    "2": "Letter/variable misread (e.g. x→y, n→u)",
    "3": "Symbol misread (e.g. +→÷, =→≠)",
    "4": "Entire term missed / not transcribed",
    "5": "Crossed-out work incorrectly included",
    "6": "Diagram not recognised or misdescribed",
    "7": "Other transcription error",
}

GRADING_ERRORS = {
    "a": "Ignored marking scheme — used own solution method",
    "b": "Did not award follow-through (ft) marks correctly",
    "c": "Did not accept equivalent/alternative correct answer",
    "d": "Penalised correct working due to transcription error",
    "e": "Incorrect M/A mark split",
    "f": "Applied wrong question's rubric",
    "g": "Over-strict on notation/presentation",
    "h": "Other grading error",
}

# ─────────────────────────────────────────────────────────────────────────────


def _rows_to_dicts(rows) -> list:
    return [
        {
            "id":              r[0],
            "paper_title":     r[1],
            "question_number": r[2],
            "confidence":      r[3],
            "flagged":         bool(r[4]),
            "review_reason":   r[5],
            "grading":         json.loads(r[6]),
            "transcription":   json.loads(r[7]) if r[7] else {},
        }
        for r in rows
    ]


_BASE_SELECT = """
    SELECT id, paper_title, question_number, overall_confidence,
           flag_for_human_review, review_reason, ai_grading, transcription
    FROM   grading_evals
"""


def get_all_unreviewed(db_path: str = DB_PATH) -> list:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(_BASE_SELECT + """
        WHERE  is_reviewed = FALSE
        ORDER  BY question_number ASC
    """).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def get_flagged_unreviewed(db_path: str = DB_PATH) -> list:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(_BASE_SELECT + """
        WHERE  flag_for_human_review = TRUE
          AND  is_reviewed = FALSE
        ORDER  BY question_number ASC
    """).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def get_fallback_unreviewed(db_path: str = DB_PATH) -> list:
    """
    Items where a fallback or critical-failure path fired during grading.
    These are the cases most likely to need correction.
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute(_BASE_SELECT + """
        WHERE  is_reviewed = FALSE
          AND  (
                review_reason LIKE '%Fallback%'
             OR review_reason LIKE '%fallback%'
             OR review_reason LIKE '%CRITICAL%'
          )
        ORDER  BY question_number ASC
    """).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def get_all_results(db_path: str = DB_PATH) -> list:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(_BASE_SELECT + """
        ORDER  BY question_number ASC
    """).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def print_question_detail(item: dict):
    g = item["grading"]
    t = item["transcription"]

    flag_str = " ⚠️  FLAGGED" if item["flagged"] else ""
    print(f"\n{'='*65}")
    print(f"  Q{item['question_number']}  |  {item['paper_title']}{flag_str}")
    print(f"  Eval ID: {item['id']}  |  Confidence: {item['confidence']:.0%}")
    if item["review_reason"]:
        print(f"  Flag reason: {item['review_reason']}")

    raw = t.get("raw_transcription", "")
    if raw:
        preview = raw[:400] + "..." if len(raw) > 400 else raw
        print(f"\n  WHAT THE AI READ (transcription):")
        print(f"  {'─'*50}")
        for line in preview.split("\n"):
            print(f"  {line}")
        print(f"  {'─'*50}")

    print(f"\n  AI GRADING:  {g['total_score']}/{g['max_score']}"
          f"  [{g.get('topic_classification', '')}]")
    for sp in g.get("sub_parts", []):
        mc = f"  ← {sp['identified_misconception']}" if sp.get("identified_misconception") else ""
        print(f"    ({sp['part_identifier']})  {sp['marks_awarded']}/{sp['marks_possible']}{mc}")
        if sp.get("detailed_critique"):
            print(f"         Critique: {sp['detailed_critique'][:150]}")

    print(f"\n  FEEDBACK TO STUDENT:")
    print(f"  {g.get('pedagogical_remedial_strategy', '')[:300]}")
    print(f"{'─'*65}")


def select_error_categories(error_dict: dict, label: str) -> list:
    print(f"\n  {label}:")
    for code, desc in error_dict.items():
        print(f"    [{code}] {desc}")
    print(f"    [0] None / not applicable")

    raw = input("  Enter code(s), comma-separated (e.g. 1,3): ").strip()
    if not raw or raw == "0":
        return []

    selected = []
    for code in raw.split(","):
        code = code.strip()
        if code in error_dict:
            selected.append(error_dict[code])
        else:
            print(f"  ⚠️  Unknown code '{code}' — skipped.")
    return selected


def handle_correction(item: dict) -> bool:
    g = item["grading"]
    q = item["question_number"]

    print(f"\n  CORRECTION WIZARD for Q{q}")
    print(f"  {'─'*50}")

    correction = dict(g)
    correction["error_analysis"] = {
        "transcription_errors":  [],
        "grading_errors":        [],
        "correct_transcription": None,
        "teacher_notes":         None,
    }

    # Step 1: Transcription
    print(f"\n  STEP 1 — Transcription Check")
    print(f"  Did the AI correctly read the student's handwriting?")
    trans_ok = input("  (y/n): ").strip().lower()

    if trans_ok == "n":
        t_errors = select_error_categories(
            TRANSCRIPTION_ERRORS,
            "What kind of transcription error occurred?"
        )
        correction["error_analysis"]["transcription_errors"] = t_errors

        print(f"\n  What should the transcription have said?")
        print(f"  (Just the specific part that was wrong)")
        correct_trans = input("  Correct reading: ").strip()
        if correct_trans:
            correction["error_analysis"]["correct_transcription"] = correct_trans

    # Step 2: Grading logic
    print(f"\n  STEP 2 — Grading Logic Check")
    print(f"  Did the AI apply the marking scheme correctly?")
    grade_ok = input("  (y/n): ").strip().lower()

    if grade_ok == "n":
        g_errors = select_error_categories(
            GRADING_ERRORS,
            "What kind of grading error occurred?"
        )
        correction["error_analysis"]["grading_errors"] = g_errors

    # Step 3: Score
    print(f"\n  STEP 3 — Score Correction")
    print(f"  Current AI score: {g['total_score']}/{g['max_score']}")
    raw = input(f"  Correct total (Enter to keep {g['total_score']}): ").strip()
    if raw:
        try:
            correction["total_score"] = int(raw)
        except ValueError:
            print("  Invalid — keeping AI score.")

    print(f"\n  Sub-part corrections (Enter to keep each):")
    corrected_parts = []
    for sp in g.get("sub_parts", []):
        raw_sp = input(
            f"    ({sp['part_identifier']}) AI: {sp['marks_awarded']}/{sp['marks_possible']} → correct: "
        ).strip()
        sp_copy = dict(sp)
        if raw_sp:
            try:
                sp_copy["marks_awarded"] = int(raw_sp)
            except ValueError:
                print(f"    Invalid — keeping {sp['marks_awarded']}")
        corrected_parts.append(sp_copy)
    correction["sub_parts"] = corrected_parts

    # Step 4: Feedback
    print(f"\n  STEP 4 — Student Feedback")
    print(f"  Current: {g.get('pedagogical_remedial_strategy','')[:200]}")
    better = input("  Better feedback (Enter to keep): ").strip()
    if better:
        correction["pedagogical_remedial_strategy"] = better

    # Step 5: Notes
    notes = input("\n  Extra notes for future reference (Enter to skip): ").strip()
    if notes:
        correction["error_analysis"]["teacher_notes"] = notes

    # Summary
    print(f"\n  {'─'*50}")
    print(f"  Summary:")
    print(f"    Score: {g['total_score']} → {correction['total_score']}/{g['max_score']}")
    if correction["error_analysis"]["transcription_errors"]:
        print(f"    Transcription errors : {correction['error_analysis']['transcription_errors']}")
    if correction["error_analysis"]["grading_errors"]:
        print(f"    Grading errors       : {correction['error_analysis']['grading_errors']}")
    if correction["error_analysis"]["correct_transcription"]:
        print(f"    Correct reading      : {correction['error_analysis']['correct_transcription']}")

    confirm = input("\n  Save? (y/n): ").strip().lower()
    if confirm == "y":
        submit_teacher_review(item["id"], is_correct=False, teacher_correction=correction)
        print("  ✅ Saved — will improve future grading on similar questions.")
    else:
        print("  ❌ Discarded.")

    return True


def prompt_review(item: dict) -> bool:
    print_question_detail(item)

    print("\n  [y] Correct")
    print("  [n] Wrong — provide correction")
    print("  [s] Skip")
    print("  [q] Quit")

    while True:
        choice = input("\n  Choice (y/n/s/q): ").strip().lower()
        if choice == "q":
            print("\n  👋 Progress saved.")
            return False
        elif choice == "s":
            print("  ⏭️  Skipped.")
            return True
        elif choice == "y":
            submit_teacher_review(item["id"], is_correct=True)
            print("  ✅ Marked correct.")
            return True
        elif choice == "n":
            return handle_correction(item)
        else:
            print("  Enter y, n, s, or q.")


def run_review_cli(mode: str = "unreviewed"):
    init_db()

    if mode == "flagged":
        queue = get_flagged_unreviewed()
        label = "flagged unreviewed"
    elif mode == "fallback":
        queue = get_fallback_unreviewed()
        label = "fallback/critical unreviewed"
    elif mode == "all":
        queue = get_all_results()
        label = "all"
    else:
        queue = get_all_unreviewed()
        label = "unreviewed"

    if not queue:
        print(f"\n✅ No {label} items found.")
        if mode == "unreviewed":
            print("   Try: python review_cli.py --all   to re-review everything")
        elif mode == "fallback":
            print("   No questions hit a fallback path — nice.")
        return

    print(f"\n{'='*65}")
    print(f"  TEACHER REVIEW  —  {len(queue)} {label} question(s)")
    print(f"  Paper: {queue[0]['paper_title']}")
    print(f"{'='*65}")

    reviewed = 0
    for item in queue:
        if not prompt_review(item):
            break
        reviewed += 1

    print(f"\n{'='*65}")
    print(f"  Session complete — {reviewed}/{len(queue)} reviewed.")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    mode = "unreviewed"
    if "--flagged-only" in sys.argv:
        mode = "flagged"
    elif "--fallback-only" in sys.argv:
        mode = "fallback"
    elif "--all" in sys.argv:
        mode = "all"
    run_review_cli(mode)