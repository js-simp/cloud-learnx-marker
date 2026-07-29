import re
from typing import Dict, Any, List, Optional

# Maps syllabus_code → curriculum schema filename in curricula/
CURRICULUM_MAP = {
    "4MA1_Higher":      "edexcel_igcse_4ma1_higher",
    "4MA1_Foundation":  "edexcel_igcse_4ma1_foundation",
    "KS3_Standard":     "uk_ks3_year7_9",
    # Add more as you build out curriculum schema files:
    # "0580_Extended":  "caie_igcse_0580_extended",
    # "0606_AddMaths":  "caie_igcse_0606_addmaths",
    # "GCE_O_Level":    "singapore_gce_o_level",
}


def normalize_student_profile(raw_profile: Dict[str, Any], topic: Optional[str] = None) -> Dict[str, Any]:
    """
    Adapts the rich Cloud LearnX JSON schema (stored in Supabase `profile_data`)
    into the flat, structured format required by worksheet_generator.py.
    """

    # ── 1. Identity & Year ───────────────────────────────────────────────────
    core      = raw_profile.get("core_identity", {})
    full_name = core.get("full_name", "Student")
    preferred = core.get("preferred_name", full_name.split()[0] if full_name else "Student")

    year_str  = str(core.get("year_group", "Year 10"))
    match     = re.search(r'\d+', year_str)
    year_int  = int(match.group()) if match else 10

    # ── 2. Curriculum ID ─────────────────────────────────────────────────────
    # Prefer an explicit curriculum_id on the profile; otherwise map from syllabus_code.
    syllabus_code = core.get("syllabus_code", "4MA1_Higher")
    curriculum_id = (
        core.get("curriculum_id")
        or CURRICULUM_MAP.get(syllabus_code)
    )
    if not curriculum_id:
        print(f"  ⚠️  No curriculum schema mapped for syllabus_code='{syllabus_code}'. "
              f"Worksheet will generate without curriculum constraints.")

    # ── 3. Flatten Mastery Matrix → topic_scores ─────────────────────────────
    mastery_matrix = raw_profile.get("mastery_matrix", {})
    flat_scores: Dict[str, float] = {}

    for category, subtopics in mastery_matrix.items():
        if isinstance(subtopics, dict):
            for subtopic, score in subtopics.items():
                score_float = float(score)
                # Store both raw key and human-readable version for flexible lookup
                flat_scores[subtopic] = score_float
                flat_scores[subtopic.replace("_", " ").title()] = score_float
        elif isinstance(subtopics, (int, float)):
            # Flat category-level score (e.g. "geometry": 0.7)
            flat_scores[category] = float(subtopics)

    # ── 4. Misconceptions ────────────────────────────────────────────────────
    diagnosis           = raw_profile.get("academic_diagnosis", {})
    raw_misconceptions  = diagnosis.get("known_misconceptions", [])
    formatted_misconceptions: List[str] = []

    for item in raw_misconceptions:
        if isinstance(item, str):
            formatted_misconceptions.append(item)
        elif isinstance(item, dict):
            tag      = item.get("tag") or item.get("topic", "General")
            severity = item.get("severity", "Medium")
            sample   = item.get("sample_error")
            desc     = f"{tag} [{severity} Severity]"
            if sample:
                desc += f" (e.g. {sample})"
            formatted_misconceptions.append(desc)

    # Active weakness tags → appended as extra misconception context
    weakness_tags = diagnosis.get("active_weakness_tags", [])
    for tag in weakness_tags:
        entry = f"Weakness in {tag}"
        if entry not in formatted_misconceptions:
            formatted_misconceptions.append(entry)

    # ── 5. Error patterns ────────────────────────────────────────────────────
    # active_weakness_tags IS the error patterns in your schema
    error_patterns = diagnosis.get("active_weakness_tags", [])

    # ── 6. Pedagogy notes ────────────────────────────────────────────────────
    pedagogy             = raw_profile.get("pedagogy_and_personalisation", {})
    interests            = pedagogy.get("interests", [])
    frustration_triggers = pedagogy.get("frustration_triggers", [])
    learning_style       = pedagogy.get("learning_style", "")
    pacing               = pedagogy.get("preferred_pacing", "")

    mindset = pedagogy.get("mindset_profile", {})
    tutor_notes = mindset.get("internal_tutor_notes", "")

    notes_parts = []
    if learning_style:
        notes_parts.append(f"Learning style: {learning_style.replace('_', ' ')}")
    if pacing:
        notes_parts.append(f"Pacing: {pacing.replace('_', ' ')}")
    if interests:
        notes_parts.append(f"Interests for word problems: {', '.join(interests)}")
    if frustration_triggers:
        notes_parts.append(f"Avoid: {'; '.join(frustration_triggers)}")
    if tutor_notes:
        notes_parts.append(f"Tutor notes: {tutor_notes}")

    strengths = diagnosis.get("strengths", [])
    if strengths:
        notes_parts.append(f"Strengths: {', '.join(strengths)}")

    teacher_notes = " | ".join(notes_parts)

    return {
        "name":                 preferred,
        "full_name":            full_name,
        "year":                 year_int,
        "curriculum_id":        curriculum_id,
        "topic_scores":         flat_scores,
        "known_misconceptions": formatted_misconceptions,
        "error_patterns":       error_patterns,
        "teacher_notes":        teacher_notes,
        "interests":            interests,
        "frustration_triggers": frustration_triggers,
        "target_grade":         core.get("target_grade"),
        "raw":                  raw_profile,   # kept for debugging
    }