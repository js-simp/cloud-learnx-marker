"""
curriculum_loader.py
─────────────────────
Loads curriculum schemas from curricula/*.json and formats them
into a prompt-injectable block for the worksheet generator.

If a curriculum schema doesn't exist yet for a student's syllabus,
it gracefully returns an empty string so the generator continues
without curriculum constraints rather than crashing.
"""

import json
from pathlib import Path
from typing import Optional

CURRICULA_DIR = Path(__file__).parent / "curricula"


def load_curriculum(curriculum_id: str) -> dict:
    path = CURRICULA_DIR / f"{curriculum_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No curriculum schema found for '{curriculum_id}'. "
            f"Available: {[p.stem for p in CURRICULA_DIR.glob('*.json')]}"
        )
    return json.loads(path.read_text())


def get_topic_constraints(curriculum_id: str, topic: str, year: Optional[int] = None) -> dict:
    """
    Returns the relevant subtopic/exclusion/formula rules for a topic.
    Handles both exam-board style (flat topics list) and KS3 style
    (organised by year_groups).
    """
    curriculum = load_curriculum(curriculum_id)

    # ── Exam board style (IGCSE/IAL) — flat topics list ──────────────────
    if "topics" in curriculum:
        for t in curriculum["topics"]:
            if t["topic"].lower() == topic.lower():
                return {
                    "curriculum_name":   curriculum.get("qualification"),
                    "board":             curriculum.get("board"),
                    "tier":              curriculum.get("tier"),
                    "calculator_policy": curriculum.get("calculator_policy"),
                    "subtopics":         t.get("subtopics", []),
                    "excluded":          t.get("excluded_at_this_level", []),
                    "command_words":     t.get("command_words_used", []),
                    "marks_range":       t.get("typical_marks_per_question", []),
                }
        # Topic not found in schema — return minimal info so generator continues
        return {
            "curriculum_name":   curriculum.get("qualification"),
            "board":             curriculum.get("board"),
            "tier":              curriculum.get("tier"),
            "calculator_policy": curriculum.get("calculator_policy"),
            "subtopics":         [],
            "excluded":          [],
            "command_words":     ["Find", "Work out", "Calculate", "Show that"],
            "marks_range":       [2, 3, 4],
        }

    # ── KS3 style — organised by year_groups ─────────────────────────────
    if "year_groups" in curriculum:
        year_key = f"Year {year}"
        if year_key not in curriculum["year_groups"]:
            raise ValueError(f"'{year_key}' not found in curriculum '{curriculum_id}'")

        year_data = curriculum["year_groups"][year_key]
        matching_topics = [
            t for t in year_data["typical_topics"]
            if topic.lower() in t.lower()
        ]

        return {
            "curriculum_name":   curriculum.get("qualification"),
            "board":             curriculum.get("board"),
            "tier":              year_key,
            "calculator_policy": curriculum.get("calculator_policy"),
            "subtopics":         matching_topics or year_data["typical_topics"],
            "excluded":          year_data.get("excluded", []),
            "command_words":     year_data.get("command_words_used", []),
            "marks_range":       year_data.get("typical_marks_per_question", []),
        }

    raise ValueError(f"Unrecognised curriculum schema structure for '{curriculum_id}'")


def build_curriculum_prompt_block(
    curriculum_id: str,
    topic: str,
    year: Optional[int] = None
) -> str:
    """
    Formats curriculum constraints as a prompt injection block.
    Returns empty string if no schema exists — generator continues gracefully.
    """
    if not curriculum_id:
        return ""

    try:
        c = get_topic_constraints(curriculum_id, topic, year)
    except FileNotFoundError as e:
        print(f"  ⚠️  {e} — continuing without curriculum constraints")
        return ""
    except (ValueError, Exception) as e:
        print(f"  ⚠️  Curriculum lookup failed: {e} — continuing without constraints")
        return ""

    subtopics_text = ""
    for s in c["subtopics"]:
        if isinstance(s, dict):
            line = f"  - {s['name']}"
            if s.get("on_formula_sheet"):
                formula = s.get("formula_text", "provided")
                line += f" [formula given: {formula}]"
            if s.get("notes"):
                line += f" — {s['notes']}"
            subtopics_text += line + "\n"
        else:
            subtopics_text += f"  - {s}\n"

    excluded_text = "\n".join(f"  - {x}" for x in c["excluded"]) \
                    if c["excluded"] else "  (none specified)"

    return f"""
CURRICULUM CONSTRAINTS — FOLLOW STRICTLY:
Qualification : {c['curriculum_name']} ({c['board']})
Level / Tier  : {c.get('tier', 'N/A')}
Calculator    : {c['calculator_policy']}

VALID SUBTOPICS FOR "{topic}" AT THIS LEVEL:
{subtopics_text.strip() if subtopics_text else '  (topic not in schema — use standard syllabus content)'}

EXCLUDED — do NOT use these methods or concepts (beyond this level):
{excluded_text}

COMMAND WORDS TO USE : {', '.join(c['command_words']) if c['command_words'] else 'Standard phrasing'}
TYPICAL MARKS / QUESTION : {c['marks_range'] if c['marks_range'] else 'Use judgement'}

Stay strictly within the subtopics and exclusions above.
Do not introduce methods, formulae, or notation the student has not yet been taught.
"""


if __name__ == "__main__":
    print(build_curriculum_prompt_block("edexcel_igcse_4ma1_higher", "Trigonometry"))
