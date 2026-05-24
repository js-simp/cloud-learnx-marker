"""
=============================================================================
  STUDENT PROGRESS TRACKER  —  student_tracker.py
=============================================================================
  Links exam reports to student profiles and tracks improvement over time.

  Usage:
      python student_tracker.py
=============================================================================
"""

import json
import sqlite3
from datetime import date
from pipeline import DB_PATH, init_db


def register_student(name: str, school: str = "") -> int:
    """Add a new student. Returns their ID."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "INSERT INTO students (name, school) VALUES (?, ?)", (name, school)
    )
    student_id = cursor.lastrowid
    conn.commit()
    conn.close()
    print(f"✅ Student registered: {name} (ID: {student_id})")
    return student_id


def list_students() -> list:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, name, school, created_at FROM students ORDER BY name"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "school": r[2], "joined": r[3]} for r in rows]


def link_attempt_to_student(
    student_id:  int,
    report_path: str,
    subject:     str = "Mathematics",
):
    """
    Reads a pipeline report JSON and saves the attempt
    against a student profile.
    """
    with open(report_path) as f:
        report = json.load(f)

    s       = report["summary"]
    conn    = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO attempts
            (student_id, paper_title, subject, total_marks, marks_awarded, percentage, report_json)
        VALUES (?,?,?,?,?,?,?)
    """, (
        student_id,
        report["paper_title"],
        subject,
        s["total_marks_possible"],
        s["total_marks_awarded"],
        s["percentage"],
        json.dumps(report),
    ))
    conn.commit()
    conn.close()
    print(f"✅ Attempt linked: {report['paper_title']} → Student ID {student_id} "
          f"({s['marks_awarded']}/{s['total_marks_possible']} = {s['percentage']}%)")


def get_student_progress(student_id: int) -> dict:
    """Return full progress history for a student."""
    conn = sqlite3.connect(DB_PATH)

    student = conn.execute(
        "SELECT name, school FROM students WHERE id = ?", (student_id,)
    ).fetchone()

    if not student:
        conn.close()
        return {}

    attempts = conn.execute("""
        SELECT paper_title, subject, attempt_date, marks_awarded, total_marks, percentage
        FROM   attempts
        WHERE  student_id = ?
        ORDER  BY attempt_date ASC
    """, (student_id,)).fetchall()

    conn.close()

    history = [
        {
            "paper":      a[0],
            "subject":    a[1],
            "date":       a[2],
            "awarded":    a[3],
            "possible":   a[4],
            "percentage": a[5],
        }
        for a in attempts
    ]

    # Topic weakness analysis across all attempts
    topic_scores = {}
    conn2 = sqlite3.connect(DB_PATH)
    topic_rows = conn2.execute("""
        SELECT topic_classification,
               SUM(total_score)  AS earned,
               SUM(max_score)    AS possible
        FROM   grading_evals
        WHERE  is_reviewed IS NOT FALSE        -- include AI + confirmed
        GROUP  BY topic_classification
    """).fetchall()
    conn2.close()

    for row in topic_rows:
        if row[2]:
            topic_scores[row[0]] = {
                "earned":     row[1],
                "possible":   row[2],
                "percentage": round(row[1] / row[2] * 100, 1),
            }

    return {
        "student_id":     student_id,
        "name":           student[0],
        "school":         student[1],
        "attempts":       history,
        "topic_analysis": topic_scores,
        "trend": {
            "first_score": history[0]["percentage"]  if history else None,
            "latest_score": history[-1]["percentage"] if history else None,
            "improvement":  round(
                history[-1]["percentage"] - history[0]["percentage"], 1
            ) if len(history) >= 2 else None,
        },
    }


def print_student_report(student_id: int):
    data = get_student_progress(student_id)
    if not data:
        print(f"❌ Student ID {student_id} not found.")
        return

    print(f"\n{'='*60}")
    print(f"  STUDENT PROFILE: {data['name']}")
    if data["school"]:
        print(f"  School: {data['school']}")
    print(f"{'='*60}")

    if not data["attempts"]:
        print("  No attempts recorded yet.")
        return

    print("\n  ATTEMPT HISTORY:")
    for a in data["attempts"]:
        print(f"  {a['date']}  {a['paper']:<35} {a['awarded']:>3}/{a['possible']:<3}  ({a['percentage']}%)")

    t = data["trend"]
    if t["improvement"] is not None:
        arrow = "▲" if t["improvement"] >= 0 else "▼"
        print(f"\n  TREND: {t['first_score']}% → {t['latest_score']}%  "
              f"{arrow} {abs(t['improvement'])}%")

    if data["topic_analysis"]:
        print("\n  TOPIC BREAKDOWN (all-time):")
        sorted_topics = sorted(
            data["topic_analysis"].items(),
            key=lambda x: x[1]["percentage"]
        )
        for topic, scores in sorted_topics:
            bar_len = int(scores["percentage"] / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            print(f"  {topic:<30} {bar} {scores['percentage']:>5}%")

    print(f"\n{'='*60}\n")


# ============================================================================
# SIMPLE CLI
# ============================================================================

if __name__ == "__main__":
    init_db()
    print("\n  STUDENT TRACKER")
    print("  [1] Register new student")
    print("  [2] List students")
    print("  [3] Link exam report to student")
    print("  [4] View student progress")

    choice = input("\n  Choose: ").strip()

    if choice == "1":
        name   = input("  Student name: ").strip()
        school = input("  School (optional): ").strip()
        register_student(name, school)

    elif choice == "2":
        students = list_students()
        if not students:
            print("  No students registered yet.")
        for s in students:
            print(f"  [{s['id']}] {s['name']} — {s['school'] or 'No school'}")

    elif choice == "3":
        sid     = int(input("  Student ID: ").strip())
        rpath   = input("  Report JSON path [exam_report.json]: ").strip() or "exam_report.json"
        subject = input("  Subject [Mathematics]: ").strip() or "Mathematics"
        link_attempt_to_student(sid, rpath, subject)

    elif choice == "4":
        sid = int(input("  Student ID: ").strip())
        print_student_report(sid)
