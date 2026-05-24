"""
=============================================================================
  TEACHER REVIEW CLI  —  review_cli.py
=============================================================================
  Run this after a pipeline run to review flagged questions and feed
  corrections back into the eval store (improving future grading).

  Usage:
      python review_cli.py
=============================================================================
"""

import json
from pipeline import get_review_queue, submit_teacher_review, DB_PATH


def run_review_cli():
    queue = get_review_queue(DB_PATH)

    if not queue:
        print("✅ No items in the review queue. All caught up!")
        return

    print(f"\n{'='*60}")
    print(f"  TEACHER REVIEW QUEUE  —  {len(queue)} item(s)")
    print(f"{'='*60}")

    for item in queue:
        print(f"\n📋 Eval ID     : {item['id']}")
        print(f"   Paper       : {item['paper_title']}")
        print(f"   Question    : {item['question_number']}")
        print(f"   Confidence  : {item['confidence']:.0%}")
        print(f"   Flag reason : {item['review_reason']}")
        print(f"\n   AI Grading  :")

        g = item["grading"]
        print(f"     Score: {g['total_score']}/{g['max_score']}")
        for sp in g.get("sub_parts", []):
            print(f"     ({sp['part_identifier']}) "
                  f"{sp['marks_awarded']}/{sp['marks_possible']}"
                  + (f" — {sp['identified_misconception']}" if sp.get("identified_misconception") else ""))

        print(f"\n   AI Feedback : {g['pedagogical_remedial_strategy'][:200]}")

        print(f"\n{'─'*60}")
        print("  Is the AI grading correct?")
        print("  [y] Yes, mark as correct")
        print("  [n] No, I'll provide a correction")
        print("  [s] Skip for now")

        choice = input("\n  Your choice (y/n/s): ").strip().lower()

        if choice == "s":
            print("  ⏭️  Skipped.")
            continue

        elif choice == "y":
            submit_teacher_review(item["id"], is_correct=True)
            print("  ✅ Marked as correct. Will be used as a future few-shot example.")

        elif choice == "n":
            print("\n  Enter the corrected total score (press Enter to keep AI score):")
            raw_score = input(f"  Total score [{g['total_score']}/{g['max_score']}]: ").strip()

            correction = dict(g)  # start from AI grading

            if raw_score:
                try:
                    correction["total_score"] = int(raw_score)
                except ValueError:
                    print("  Invalid input — keeping AI score.")

            print("\n  Enter any correction notes (or press Enter to skip):")
            notes = input("  Notes: ").strip()
            if notes:
                correction["teacher_notes"] = notes

            submit_teacher_review(item["id"], is_correct=False, teacher_correction=correction)
            print("  ✅ Correction saved. Will be used as a corrective few-shot example.")

        else:
            print("  ❓ Unrecognised input — skipped.")

    print(f"\n{'='*60}")
    print("  Review session complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run_review_cli()
