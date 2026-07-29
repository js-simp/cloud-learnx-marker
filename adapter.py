import re
from typing import Dict, Any, List

def normalize_student_profile(raw_profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adapts the rich Cloud LearnX JSON schema (or Supabase record) into 
    the flat, structured format required by worksheet_generator.py.
    """
    # 1. Identity & Year Parsing
    core = raw_profile.get("core_identity", {})
    full_name = core.get("full_name", "Student")
    preferred_name = core.get("preferred_name", full_name.split()[0] if full_name else "Student")
    
    year_str = str(core.get("year_group", "Year 10"))
    match = re.search(r'\d+', year_str)
    year_int = int(match.group()) if match else 10

    # 2. Curriculum Mapping
    syllabus_code = core.get("syllabus_code", "4MA1_Higher").lower()
    curriculum_id = core.get("curriculum_id") or f"edexcel_igcse_{syllabus_code}"

    # 3. Flatten Mastery Matrix -> Topic Scores
    mastery_matrix = raw_profile.get("mastery_matrix", {})
    flat_scores: Dict[str, float] = {}
    
    for category, subtopics in mastery_matrix.items():
        if isinstance(subtopics, dict):
            for subtopic, score in subtopics.items():
                flat_scores[subtopic] = float(score)
                # Normalize key formats e.g. "algebraic_fractions" -> "Algebraic Fractions"
                clean_key = subtopic.replace("_", " ").title()
                flat_scores[clean_key] = float(score)
        elif isinstance(subtopics, (int, float)):
            flat_scores[category] = float(subtopics)

    # 4. Extract Misconceptions
    diagnosis = raw_profile.get("academic_diagnosis", {})
    raw_misconceptions = diagnosis.get("known_misconceptions", [])
    formatted_misconceptions: List[str] = []

    for item in raw_misconceptions:
        if isinstance(item, str):
            formatted_misconceptions.append(item)
        elif isinstance(item, dict):
            tag = item.get("tag") or item.get("topic", "General")
            severity = item.get("severity", "Medium")
            sample = item.get("sample_error")
            
            desc = f"{tag} [{severity} Severity]"
            if sample:
                desc += f" (e.g. {sample})"
            formatted_misconceptions.append(desc)

    # Add active weakness tags as misconceptions if empty
    weakness_tags = diagnosis.get("active_weakness_tags", [])
    for tag in weakness_tags:
        if tag not in formatted_misconceptions:
            formatted_misconceptions.append(f"Weakness in {tag}")

    # 5. Build Rich Pedagogy & Context Block
    pedagogy = raw_profile.get("pedagogy_and_personalisation", {})
    frustration_triggers = pedagogy.get("frustration_triggers", [])
    interests = pedagogy.get("interests", [])
    
    notes_parts = []
    if interests:
        notes_parts.append(f"Interests for word problems: {', '.join(interests)}.")
    if frustration_triggers:
        notes_parts.append(f"Pedagogical Constraints/Frustrations: {', '.join(frustration_triggers)}.")
    
    teacher_notes = " ".join(notes_parts)

    return {
        "name": preferred_name,
        "full_name": full_name,
        "year": year_int,
        "curriculum_id": curriculum_id,
        "topic_scores": flat_scores,
        "known_misconceptions": formatted_misconceptions,
        "error_patterns": diagnosis.get("error_patterns", []),
        "teacher_notes": teacher_notes,
        "interests": interests,
        "frustration_triggers": frustration_triggers,
        "raw": raw_profile
    }