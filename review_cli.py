"""
=============================================================================
  TEACHER REVIEW CLI  —  review_cli.py  (v2)
=============================================================================
  Lets you review ALL graded questions, not just flagged ones.
  Corrections feed back into the eval store as few-shot examples.

  Usage:
      python review_cli.py                  # review all unreviewed
      python review_cli.py --flagged-only   # review only flagged
      python review_cli.py --all            # re-review everything including reviewed
=============================================================================
"""

import json
import sys
import sqlite3
from pipeline import submit_teacher_review, DB_PATH, init_db


def get_all_unreviewed(db_path: str = DB_PATH) -> list:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT id, paper_title, question_number, overall_confidence,
               flag_for_human_review, review_reason, ai_grading, transcription
        FROM   grading_evals
        WHERE  is_reviewed = FALSE
        ORDER  BY question_number ASC
    """).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def get_flagged_unreviewed(db_path: str = DB_PATH) -> list:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT id, paper_title, question_number, overall_confidence,
               flag_for_human_review, review_reason, ai_grading, transcription
        FROM   grading_evals
        WHERE  flag_for_human_review = TRUE
          AND  is_reviewed = FALSE
        ORDER  BY question_number ASC
    """).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def get_all_results(db_path: str = DB_PATH) -> list:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT id, paper_title, question_number, overall_confidence,
               flag_for_human_review, review_reason, ai_grading, transcription
        FROM   grading_evals
        ORDER  BY question_number ASC
    """).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


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


def print_question_detail(item: dict):
    g = item["grading"]
    t = item["transcription"]

    flag_str = " ⚠️  FLAGGED" if item["flagged"] else ""
    print(f"\n{'='*65}")
    print(f"  Q{item['question_number']}  |  {item['paper_title']}{flag_str}")
    print(f"  Eval ID: {item['id']}  |  Confidence: {item['confidence']:.0%}")
    if item["review_reason"]:
        print(f"  Flag reason: {item['review_reason']}")

    # Transcription summary
    raw = t.get("raw_transcription", "")
    if raw:
        preview = raw[:300] + "..." if len(raw) > 300 else raw
        print(f"\n  STUDENT WROTE:\n  {preview}")

    # AI grading breakdown
    print(f"\n  AI GRADING:  {g['total_score']}/{g['max_score']}  [{g.get('topic_classification','')}]")
    for sp in g.get("sub_parts", []):
        mc = f"  ← {sp['identified_misconception']}" if sp.get("identified_misconception") else ""
        print(f"    ({sp['part_identifier']})  {sp['marks_awarded']}/{sp['marks_possible']}{mc}")
        if sp.get("detailed_critique"):
            print(f"         {sp['detailed_critique'][:120]}")

    print(f"\n  FEEDBACK TO STUDENT:")
    print(f"  {g.get('pedagogical_remedial_strategy', '')[:300]}")
    print(f"{'─'*65}")


def prompt_review(item: dict) -> bool:
    """
    Interactively review one item.
    Returns True to continue, False to quit.
    """
    print_question_detail(item)

    print("\n  What would you like to do?")
    print("  [y] Correct — mark as correct, use as positive example")
    print("  [n] Wrong   — provide correction")
    print("  [s] Skip    — leave unreviewed for now")
    print("  [q] Quit    — save progress and exit")

    while True:
        choice = input("\n  Your choice (y/n/s/q): ").strip().lower()

        if choice == "q":
            print("\n  👋 Exiting review session. Progress saved.")
            return False

        elif choice == "s":
            print("  ⏭️  Skipped.")
            return True

        elif choice == "y":
            submit_teacher_review(item["id"], is_correct=True)
            print("  ✅ Marked correct — added to few-shot example pool.")
            return True

        elif choice == "n":
            return handle_correction(item)

        else:
            print("  ❓ Please enter y, n, s, or q.")


def handle_correction(item: dict) -> bool:
    """Walk teacher through providing a correction."""
    g = item["grading"]

    print(f"\n  CORRECTION for Q{item['question_number']}")
    print(f"  Current AI score: {g['total_score']}/{g['max_score']}")
    print(f"  (Press Enter to keep the current value)\n")

    correction = dict(g)  # start from AI grading as base

    # Correct total score
    raw = input(f"  Correct total score [{g['total_score']}/{g['max_score']}]: ").strip()
    if raw:
        try:
            correction["total_score"] = int(raw)
        except ValueError:
            print("  Invalid number — keeping AI score.")

    # Correct sub-parts
    print(f"\n  Sub-part corrections (press Enter to keep AI score for each):")
    corrected_parts = []
    for sp in g.get("sub_parts", []):
        raw_sp = input(
            f"    ({sp['part_identifier']}) AI gave {sp['marks_awarded']}/{sp['marks_possible']} — correct score: "
        ).strip()
        sp_copy = dict(sp)
        if raw_sp:
            try:
                sp_copy["marks_awarded"] = int(raw_sp)
            except ValueError:
                print(f"    Invalid — keeping {sp['marks_awarded']}")
        corrected_parts.append(sp_copy)
    correction["sub_parts"] = corrected_parts

    # Error classification
    print(f"\n  What was the main error? (press Enter to skip)")
    print(f"  Examples: 'sign error', 'wrong formula', 'arithmetic mistake',")
    print(f"            'method correct but accuracy lost', 'correct answer no working'")
    error_note = input("  Error type: ").strip()
    if error_note:
        correction["teacher_error_note"] = error_note

    # Feedback correction
    print(f"\n  Current feedback: {g.get('pedagogical_remedial_strategy','')[:200]}")
    better_feedback = input("  Better feedback (or Enter to keep): ").strip()
    if better_feedback:
        correction["pedagogical_remedial_strategy"] = better_feedback

    # Confirm
    print(f"\n  Summary of correction:")
    print(f"    Score: {g['total_score']} → {correction['total_score']} / {g['max_score']}")
    if error_note:
        print(f"    Error type: {error_note}")
    confirm = input("\n  Save this correction? (y/n): ").strip().lower()

    if confirm == "y":
        submit_teacher_review(item["id"], is_correct=False, teacher_correction=correction)
        print("  ✅ Correction saved — will be used as corrective few-shot example.")
    else:
        print("  ❌ Correction discarded.")

    return True


def run_review_cli(mode: str = "unreviewed"):
    init_db()

    if mode == "flagged":
        queue = get_flagged_unreviewed()
        label = "flagged unreviewed"
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
        return

    print(f"\n{'='*65}")
    print(f"  TEACHER REVIEW  —  {len(queue)} {label} question(s)")
    print(f"  Paper: {queue[0]['paper_title']}")
    print(f"{'='*65}")
    print(f"  Controls: [y] correct  [n] wrong  [s] skip  [q] quit")

    reviewed = 0
    for item in queue:
        should_continue = prompt_review(item)
        reviewed += 1
        if not should_continue:
            break

    print(f"\n{'='*65}")
    print(f"  Session complete — reviewed {reviewed}/{len(queue)} question(s).")
    print(f"  These corrections will improve grading on future papers.")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    mode = "unreviewed"
    if "--flagged-only" in sys.argv:
        mode = "flagged"
    elif "--all" in sys.argv:
        mode = "all"

    run_review_cli(mode)