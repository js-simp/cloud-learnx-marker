"""
=============================================================================
  WORKSHEET GENERATOR — Claude Edition  (worksheet_generator.py)
=============================================================================
  Same pipeline as before, now on Claude Sonnet 5, with:
    - Prompt caching for static context (macro reference + sample questions)
      that repeats on every question-generation call within a worksheet.
    - LIVE RAG RETRIEVAL from the tikz_library Supabase table instead of
      dumping a static batch of files. Each diagram question queries the
      library using its specific topic_aspect, pulling only the 3-4 most
      relevant diagrams — precise, and scales to any library size.
=============================================================================
"""

import os
import re
import json
import uuid
import shutil
import subprocess
import traceback
from pathlib import Path
from typing import Optional, List
from datetime import date

from pydantic import BaseModel, Field
from dotenv import load_dotenv

from google import genai
from google.genai import types as genai_types
from supabase import create_client

from claude_client import (
    generate_structured, generate_text,
    cached_block, plain_block,
    MODEL_SONNET, MODEL_HAIKU,
)
from curriculum_loader import build_curriculum_prompt_block

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
TEMPLATE_DIR  = Path(__file__).parent / "template"
JOBS_DIR      = Path(__file__).parent / "worksheet_jobs"
MAX_RETRIES   = 3
JOBS_DIR.mkdir(exist_ok=True)

EMBED_MODEL       = "gemini-embedding-001"
EMBED_DIMENSIONS  = 768
TIKZ_MATCH_COUNT  = 4          # how many diagrams to retrieve per question

_gemini_client   = genai.Client()
_supabase_client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


# ── Static reference content — these get cached, never change per-call ───────
MACRO_REFERENCE = r"""
AVAILABLE LATEX MACROS (use ONLY these for answer boxes):

QUESTION STRUCTURE:
  \begin{question} ... \end{question}     — wraps each question, auto-numbers, auto-totals marks
  \partq{a}  \partq{b}  etc.             — sub-part labels inside a question

ANSWER MACROS (always place at end of each part, right-aligned):
  \answerplain{marks}                    — dotted line only         e.g. \answerplain{3}
  \answerunit{unit}{marks}               — dotted line + unit       e.g. \answerunit{cm}{2}
  \answerprefix{prefix}{marks}           — prefix + dotted line     e.g. \answerprefix{\$}{2}
  \answereq{variable}{marks}             — x = dotted line          e.g. \answereq{x}{2}
  \answerequnit{variable}{unit}{marks}   — x = dotted line + unit   e.g. \answerequnit{v}{m/s}{3}
  \answerlines{num_lines}{marks}         — ruled lines for written explanation
  \answercoord{marks}                    — coordinate pair ( . , . )
  \answermarks{marks}                    — marks only, no answer line (use for show-that questions)
  \answermcq{A}{B}{C}{D}{marks}          — 4-option MCQ with tickboxes

SPACING:
  \vspace{Xcm}    — vertical space for working. Use generously (4cm minimum per part).

MATHS:
  Inline:  $...$   e.g. $x^2 + 3x - 2 = 0$
  Display: \[ ... \]  for standalone equations

TIKZ DIAGRAMS:
  Use standard tikz. Available libraries: angles, quotes, calc, 3dplot.
  Always wrap diagrams in \begin{center}...\end{center}.
  Use [scale=0.8] or similar to ensure diagrams fit the page width.

DO NOT invent new macros. DO NOT use \begin{exam} or similar — it does not exist.
"""

SAMPLE_QUESTIONS = r"""
EXAMPLE QUESTION FILES (study these for style and structure):

--- EXAMPLE: Geometry with tikz diagram (q1.tex style) ---
\begin{question}
\noindent The diagram shows two right-angled triangles, $ABD$ and $CDE$.
$ADC$ and $BDE$ are straight lines intersecting at point $D$.

\begin{center}
\begin{tikzpicture}[scale=0.6]
    \draw[thick] (-6, 0) node[below]{$A$} -- (8.5, 0) node[below]{$C$};
    \draw[thick] (-6, 8) node[above]{$B$} -- (3, -4) node[below]{$E$};
    \draw[thick] (-6, 0) -- (-6, 8);
    \draw[thick] (3, -4) -- (8.33, 0);
    \draw (-5.6, 0) -- (-5.6, 0.4) -- (-6, 0.4);
    \draw (2.76, -3.68) -- (3.08, -3.44) -- (3.32, -3.76);
    \node at (0.3, 0.4) {$D$};
    \node at (-6.5, 4) {$8$ cm};
    \node at (-3, -0.5) {$6$ cm};
    \node at (5, 0.5) {$12.5$ cm};
\end{tikzpicture}
\end{center}

\noindent $AB = 8$ cm, $AD = 6$ cm, $CD = 12.5$ cm.
Work out the length of $CE$.
\vspace{4.5cm}
\begin{flushright}
    \answerunit{cm}{3}
\end{flushright}
\end{question}

--- EXAMPLE: Multi-part algebra (q3.tex style) ---
\begin{question}
$y$ is inversely proportional to $x^n$, where $n$ is an integer.

The table shows some values of $x$ and $y$.

\begin{center}
\begin{tabular}{c|ccc}
$x$ & 3 & 6 & $q$ \\
\hline
$y$ & 40 & 5 & 0.625 \\
\end{tabular}
\end{center}

\begin{enumerate}
    \item[(a)] Find the value of $n$.
    \vspace{4cm}
    \answereq{n}{2}

    \item[(b)] Find a formula for $y$ in terms of $x$.
    \vspace{2cm}
    \answereq{y}{2}

    \item[(c)] Find the value of $q$.
    \vspace{1.5cm}
    \answereq{q}{2}
\end{enumerate}
\end{question}

--- EXAMPLE: Word problem (q4.tex style) ---
\begin{question}
A farmer buys 749 sheep for a total cost of $C$.\\
He sells 700 of the sheep for $C$.\\
The farmer then sells the remaining 49 sheep at the same price per sheep.\\
Work out the percentage profit that the farmer makes.
\vspace{4cm}
\answerplain{2}
\end{question}

--- EXAMPLE: Table with probability ---
\begin{question}
A six-sided dice is rolled once. The table shows the probabilities of some events.

\begin{center}
\renewcommand{\arraystretch}{1.6}
\setlength{\arrayrulewidth}{1.2pt}
\begin{tabular}{|>{\centering\arraybackslash}m{2.8cm}|
                  >{\centering\arraybackslash}m{2.8cm}|
                  >{\centering\arraybackslash}m{2.8cm}|}
\hline
Event & Even number & Prime number \\ \hline
Probability & $\dfrac{1}{2}$ & $\dfrac{1}{3}$ \\ \hline
\end{tabular}
\end{center}

If the dice is rolled 90 times, estimate the number of times it will show a prime number.
\vspace{4cm}
\answerplain{2}
\end{question}
"""


# ============================================================================
# SECTION 1 — PYDANTIC SCHEMAS  (unchanged from Gemini version)
# ============================================================================

class QuestionPlan(BaseModel):
    number:           int
    topic_aspect:     str  = Field(description="Specific aspect of the topic, e.g. 'SOH CAH TOA — finding a side'")
    difficulty:       str  = Field(description="easy / medium / hard")
    question_type:    str  = Field(description="single_part / multi_part / word_problem / diagram / table / mcq / show_that")
    marks:            int
    has_diagram:      bool
    misconception_targeted: Optional[str] = Field(default=None)
    notes:            str  = Field(default="", description="Brief generation note for the AI")

class WorksheetPlan(BaseModel):
    title:                   str
    num_questions:           int
    total_marks_estimate:    int
    difficulty_distribution: str
    pedagogical_rationale:   str  = Field(description="Why this structure suits this student")
    questions:               List[QuestionPlan]

class GeneratedQuestion(BaseModel):
    number:       int
    tex_content:  str  = Field(description="Complete LaTeX content for this question, ready to \\input{}")
    marks:        int
    answer:       str  = Field(description="The correct final answer(s)")
    mark_scheme:  str  = Field(description="Mark scheme in Edexcel format: M1 for..., A1 for..., etc.")
    topic_aspect: str


# ============================================================================
# SECTION 2 — LATEX ASSEMBLY  (unchanged — no AI)
# ============================================================================

def build_config_tex(meta: dict) -> str:
    return rf"""
% Auto-generated by Cloud LearnX Worksheet Generator
\newcommand{{\examDate}}{{{meta['date']}}}
\newcommand{{\examBoard}}{{{meta['board']}}}
\newcommand{{\examSubject}}{{{meta['subject']}}}
\newcommand{{\examPaper}}{{{meta['paper_title']}}}
\newcommand{{\examTier}}{{{meta['tier']}}}
\newcommand{{\examCode}}{{{meta['code']}}}
\newcommand{{\examTime}}{{{meta['time']}}}
\newcommand{{\totalMarks}}{{\total{{totalmarks}}}}
"""


def build_main_tex(num_questions: int, title: str) -> str:
    question_inputs = "\n".join([
        f"\\input{{questions/q{i}}}\n\\clearpage" if i < num_questions
        else f"\\input{{questions/q{i}}}"
        for i in range(1, num_questions + 1)
    ])
    return rf"""\documentclass[11pt]{{article}}
\input{{layout/packages}}
\input{{config}}
\input{{layout/macros}}

\renewcommand{{\familydefault}}{{\sfdefault}}

\newcounter{{totalmarks}}
\newcounter{{questionmarks}}
\newcounter{{questionNum}}
\regtotcounter{{totalmarks}}

\begin{{document}}
\input{{cover}}
\newpage

\booltrue{{drawborder}}
\newgeometry{{left=0.6in, right=0.6in, top=2cm, bottom=2cm}}
\pagestyle{{plain}}

\firstpageheader{{ALL}}

{question_inputs}

\paperTotal
\end{{document}}
"""


def build_cover_tex(student_name: str, worksheet_title: str) -> str:
    return rf"""
\pagestyle{{empty}}
\begin{{center}}
    \vspace*{{2cm}}
    {{\Huge \textbf{{\examBoard}}}} \\[5mm]
    {{\LARGE \textbf{{\examSubject}}}} \\[3mm]
    {{\Large \examPaper}} \\[8mm]
    \begin{{tcolorbox}}[colback=white, colframe=black, arc=4mm, width=0.7\textwidth,
                       boxrule=1.5pt, top=4mm, bottom=4mm]
        \centering
        {{\large \textbf{{Student:}}}} {student_name} \\[3mm]
        {{\large \textbf{{Date:}}}} \examDate \\[3mm]
        {{\large \textbf{{Topic:}}}} \examTier
    \end{{tcolorbox}}
    \vspace{{5mm}}
    {{\large \textbf{{Instructions:}}}}\\[2mm]
    \begin{{itemize}}[leftmargin=3cm]
        \item Answer ALL questions.
        \item Show ALL working — method marks are awarded for correct steps.
        \item Write answers in the spaces provided.
    \end{{itemize}}
\end{{center}}
\newpage
"""


def assemble_latex_project(job_dir, meta, student_name, generated_qs, worksheet_plan):
    (job_dir / "layout").mkdir(exist_ok=True)
    (job_dir / "questions").mkdir(exist_ok=True)
    (job_dir / "assets").mkdir(exist_ok=True)

    for f in ["packages.tex", "macros.tex"]:
        src = TEMPLATE_DIR / "layout" / f
        dst = job_dir / "layout" / f
        if src.exists():
            shutil.copy(src, dst)
        else:
            print(f"  ⚠️  Template file missing: {src}")

    assets_src = TEMPLATE_DIR / "assets"
    if assets_src.exists():
        for asset in assets_src.iterdir():
            shutil.copy(asset, job_dir / "assets" / asset.name)

    (job_dir / "config.tex").write_text(build_config_tex(meta))
    (job_dir / "cover.tex").write_text(build_cover_tex(student_name, meta['paper_title']))
    (job_dir / "main.tex").write_text(build_main_tex(len(generated_qs), meta['paper_title']))

    for q in generated_qs:
        (job_dir / "questions" / f"q{q.number}.tex").write_text(q.tex_content)

    print(f"  ✅ LaTeX project assembled — {len(generated_qs)} questions")


# ============================================================================
# SECTION 3 — TIKZ LIBRARY RETRIEVAL  (live RAG, replaces static file dump)
# ============================================================================

def retrieve_tikz_diagrams(query: str, n: int = TIKZ_MATCH_COUNT) -> str:
    """
    Embeds the query and searches the tikz_library table in Supabase for the
    N most relevant diagrams. Returns a formatted context block ready to
    inject into the question-generation prompt.

    Uses RETRIEVAL_QUERY task type (asymmetric to the RETRIEVAL_DOCUMENT
    task type used when the library was indexed) for best match quality.
    """
    try:
        embed_response = _gemini_client.models.embed_content(
            model=EMBED_MODEL,
            contents=query,
            config=genai_types.EmbedContentConfig(
                output_dimensionality=EMBED_DIMENSIONS,
                task_type="RETRIEVAL_QUERY",
            ),
        )
        query_embedding = embed_response.embeddings[0].values

        results = _supabase_client.rpc("match_tikz_library", {
            "query_embedding": query_embedding,
            "match_count": n,
        }).execute()

        if not results.data:
            print(f"    ⚠️  No tikz matches found for: '{query}'")
            return ""

        context = "TIKZ DIAGRAM REFERENCE EXAMPLES (study these for style — pick the closest match and adapt, or compose a new one in the same style):\n"
        for r in results.data:
            context += f"\n--- {r['filename']} (similarity {r['similarity']:.2f}) ---\n"
            context += f"% {r['description']}\n"
            context += r['tex_content'] + "\n"

        print(f"    📐 Retrieved {len(results.data)} tikz reference(s) for: '{query}'")
        return context

    except Exception as e:
        print(f"    ⚠️  Tikz retrieval failed: {e} — proceeding without diagram references")
        return ""


# ============================================================================
# SECTION 4 — AI PLANNING PASS  (Claude, no caching needed — called once)
# ============================================================================

def plan_worksheet(student_profile: dict, topic: str) -> WorksheetPlan:
    print("  🧠 Normalising profile & planning worksheet structure...")

    # Normalize profile via adapter
    profile = normalize_student_profile(student_profile)

    year           = profile["year"]
    weaknesses     = profile["known_misconceptions"]
    topic_scores   = profile["topic_scores"]
    error_patterns = profile["error_patterns"]
    notes          = profile["teacher_notes"]
    curriculum_id  = profile["curriculum_id"]
    interests      = profile["interests"]
    frustrations   = profile["frustration_triggers"]

    # Fuzzy match topic score lookup
    topic_score = topic_scores.get(topic) or topic_scores.get(topic.replace("_", " ").title())
    score_note  = f"Current mastery score on {topic}: {topic_score:.0%}" if topic_score is not None else "No prior data on this topic."

    curriculum_block = ""
    if curriculum_id:
        curriculum_block = build_curriculum_prompt_block(curriculum_id, topic, year)

    user_message = f"""
    You are a highly experienced mathematics tutor designing a personalised practice worksheet.

    STUDENT PROFILE:
    - Name: {profile['name']}
    - Year / Grade: Year {year}
    - Topic for this worksheet: {topic}
    - {score_note}
    - Known misconceptions: {', '.join(weaknesses) if weaknesses else 'None recorded yet'}
    - Common error patterns: {', '.join(error_patterns) if error_patterns else 'None recorded yet'}
    - Student Interests: {', '.join(interests) if interests else 'General Science'}
    - Pedagogy Notes & Avoidances: {notes or 'None'}

    {curriculum_block}

    WORKSHEET PLANNING RULES:
    - Minimum 12 questions. For Year 10+, aim for 14-18 questions.
    - Start with 2-3 confidence-building easy questions.
    - Build up through medium questions that test core method.
    - Include 2-4 challenging questions that stretch the student.
    - Include multi-part questions for complex topics.
    - If student has interests (e.g. robotics, space, gaming), weave them naturally into word problems.
    - Respect frustration triggers (e.g., if "avoid dense word problems" is specified, keep scenarios concise).
    - Vary question types: diagrams, tables, word problems, show-that, algebraic manipulation.
    - Total marks should be proportional to difficulty — typically 40-70 marks.

    Plan the complete worksheet using the tool provided.
    """

    plan = generate_structured(
        system_blocks=[plain_block("You are an expert mathematics curriculum designer.")],
        user_message=user_message,
        output_model=WorksheetPlan,
        tool_name="submit_worksheet_plan",
        model=MODEL_SONNET,
        max_tokens=4096,
        temperature=0.7,
    )
    print(f"  ✅ Plan: {plan.num_questions} questions, ~{plan.total_marks_estimate} marks")
    print(f"     Distribution: {plan.difficulty_distribution}")
    return plan


# ============================================================================
# SECTION 5 — AI QUESTION GENERATION PASS  (Claude, WITH prompt caching)
# ============================================================================

def generate_question(
    q_plan:         QuestionPlan,
    topic:          str,
    student_profile: dict,
    prev_questions: List[str] = None,
) -> GeneratedQuestion:
    """
    Generate one question. Macro reference + sample questions are CACHED
    system blocks (identical across every call in a worksheet). Tikz
    diagrams (if needed) are retrieved LIVE per-question via RAG — this
    content is dynamic (different per question) so it is NOT cached.
    """
    prev_questions = prev_questions or []
    year = student_profile.get("year", 10)

    prev_context = ""
    if prev_questions:
        prev_context = "\nQUESTIONS ALREADY GENERATED (do NOT repeat similar numbers/scenarios):\n"
        prev_context += "\n".join(f"Q{i+1}: {q}" for i, q in enumerate(prev_questions))

    curriculum_id = student_profile.get("curriculum_id")
    curriculum_block = ""
    if curriculum_id:
        curriculum_block = build_curriculum_prompt_block(curriculum_id, topic, year)

    # ── System blocks: static content first (cached) ──────────────────────
    system_blocks = [
        cached_block(MACRO_REFERENCE),
        cached_block(SAMPLE_QUESTIONS),
    ]
    if curriculum_block:
        # Cached too — identical for every question in this worksheet (same topic+year)
        system_blocks.append(cached_block(curriculum_block))

    # ── Live RAG retrieval — dynamic per question, NOT cached ─────────────
    tikz_context = ""
    if q_plan.has_diagram:
        query = f"{topic} — {q_plan.topic_aspect}"
        tikz_context = retrieve_tikz_diagrams(query, n=TIKZ_MATCH_COUNT)

    user_message = f"""
Generate Question {q_plan.number} for a Year {year} student on the topic: {topic}

{prev_context}

QUESTION SPECIFICATION:
- Topic aspect: {q_plan.topic_aspect}
- Difficulty: {q_plan.difficulty}
- Type: {q_plan.question_type}
- Marks: {q_plan.marks}
- Needs diagram: {q_plan.has_diagram}
- Misconception to target: {q_plan.misconception_targeted or 'None — general practice'}
- Notes: {q_plan.notes or 'None'}

{tikz_context}

REQUIREMENTS:
1. Write the complete LaTeX for this question — everything inside a question .tex file.
2. Use ONLY the macros listed in AVAILABLE LATEX MACROS.
3. Include generous \\vspace{{Xcm}} for working space.
4. If the question has a diagram, adapt one of the TIKZ DIAGRAM REFERENCE EXAMPLES above
   to fit this question's specific numbers/labels, or compose a new one closely following
   their style if none fit well. Do not invent an unrelated diagram style.
5. Make the question realistic, with clean numbers where possible.
6. For multi-part questions, use \\begin{{enumerate}} with \\item[(a)] etc.
7. Provide: the correct answer, and a mark scheme in Edexcel format (M1 for..., A1 for...).
8. Stay strictly within the CURRICULUM CONSTRAINTS provided in system context — do
   not use excluded methods/formulae, and use the specified command words.

tex_content must be valid LaTeX starting with \\begin{{question}} and ending with \\end{{question}}.
"""

    q = generate_structured(
        system_blocks=system_blocks,
        user_message=user_message,
        output_model=GeneratedQuestion,
        tool_name="submit_question",
        model=MODEL_SONNET,
        max_tokens=4096,
        temperature=0.4,
    )
    q.number = q_plan.number
    return q


# ============================================================================
# SECTION 6 — LATEX COMPILE + FIX LOOP  (fix uses Haiku — cheap, mechanical)
# ============================================================================

def compile_latex(job_dir: Path) -> tuple:
    try:
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
            cwd=job_dir, capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "main.tex"],
                cwd=job_dir, capture_output=True, text=True, timeout=120,
            )
            return True, ""
        log = result.stdout + result.stderr
        return False, extract_latex_errors(log)
    except subprocess.TimeoutExpired:
        return False, "Compilation timed out after 120 seconds"
    except FileNotFoundError:
        return False, "pdflatex not found — run: sudo apt-get install texlive-latex-extra"


def extract_latex_errors(log: str) -> str:
    error_lines = []
    lines = log.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("!") or "Error" in line or "Undefined" in line:
            error_lines.extend(lines[max(0, i-1):min(len(lines), i+5)])
            error_lines.append("---")
    return "\n".join(error_lines[:50]) if error_lines else log[-2000:]


def fix_question_tex(q_number: int, bad_tex: str, error_log: str) -> str:
    """Cheap mechanical fix — use Haiku, not Sonnet, since this is a simple repair task."""
    user_message = f"""
The LaTeX for Question {q_number} caused a compilation error.

COMPILE ERROR:
{error_log}

BROKEN TEX CONTENT:
{bad_tex}

Fix the LaTeX so it compiles correctly.
Return ONLY the corrected LaTeX content for this question
(starting with \\begin{{question}} and ending with \\end{{question}}).
No explanation — only the fixed LaTeX.
"""
    fixed = generate_text(
        system_blocks=[cached_block(MACRO_REFERENCE)],
        user_message=user_message,
        model=MODEL_HAIKU,
        max_tokens=4096,
        temperature=0.1,
    )
    fixed = re.sub(r"^```(?:latex)?\n?", "", fixed)
    fixed = re.sub(r"\n?```$", "", fixed)
    return fixed.strip()


def compile_with_fix_loop(job_dir: Path, questions: List[GeneratedQuestion]) -> bool:
    for attempt in range(MAX_RETRIES):
        print(f"  🔨 Compile attempt {attempt + 1}/{MAX_RETRIES}...")
        success, error_log = compile_latex(job_dir)
        if success:
            print(f"  ✅ Compiled successfully")
            return True
        print(f"  ❌ Compile failed:\n{error_log[:300]}")
        if attempt == MAX_RETRIES - 1:
            return False

        fixed_any = False
        for q in questions:
            q_file = job_dir / "questions" / f"q{q.number}.tex"
            q_tex  = q_file.read_text()
            print(f"  🔧 Attempting to fix Q{q.number} (via Haiku)...")
            fixed_tex = fix_question_tex(q.number, q_tex, error_log)
            if fixed_tex and fixed_tex != q_tex:
                q_file.write_text(fixed_tex)
                q.tex_content = fixed_tex
                fixed_any = True
                print(f"  🔧 Q{q.number} rewritten")
                break
        if not fixed_any:
            print("  ⚠️  Could not identify which question to fix — retrying as-is")
    return False


# ============================================================================
# SECTION 7 — MARK SCHEME ASSEMBLER  (unchanged — no AI)
# ============================================================================

def build_mark_scheme(student_name, topic, worksheet_plan, questions) -> dict:
    return {
        "paper_title":    f"{topic} Worksheet — {student_name}",
        "subject":        "Mathematics",
        "generated_date": date.today().isoformat(),
        "total_marks":    sum(q.marks for q in questions),
        "questions": [
            {
                "question_number": q.number,
                "topic_aspect":    q.topic_aspect,
                "total_marks":     q.marks,
                "correct_answer":  q.answer,
                "mark_scheme":     q.mark_scheme,
                "misconception_targeted": worksheet_plan.questions[q.number - 1].misconception_targeted,
            }
            for q in questions
        ]
    }


# ============================================================================
# SECTION 8 — MAIN ENTRY POINT
# ============================================================================

def generate_worksheet(
    student_profile:  dict,
    topic:            str,
    output_dir:       Optional[Path] = None,
    board:            str = "Cloud LearnX",
    subject:          str = "Mathematics",
) -> dict:
    """
    Full worksheet generation pipeline.

    NOTE: tikz_samples_dir parameter has been removed — diagrams are now
    retrieved live from the indexed tikz_library table in Supabase via RAG,
    rather than dumping a static batch of files into every prompt.
    """
    job_id  = str(uuid.uuid4())[:8]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)

    student_name = student_profile.get("name", "Student")
    year         = student_profile.get("year", 10)

    print(f"\n{'='*60}")
    print(f"  WORKSHEET GENERATOR (Claude + RAG tikz) — Job {job_id}")
    print(f"  Student: {student_name} | Year {year} | Topic: {topic}")
    print(f"{'='*60}")

    try:
        plan = plan_worksheet(student_profile, topic)

        questions      = []
        prev_summaries = []

        print(f"\n  Generating {plan.num_questions} questions...")
        for q_plan in plan.questions:
            print(f"  → Q{q_plan.number}: {q_plan.topic_aspect} [{q_plan.difficulty}, {q_plan.marks}m]")
            try:
                q = generate_question(
                    q_plan, topic, student_profile, prev_summaries,
                )
                questions.append(q)
                prev_summaries.append(q_plan.topic_aspect)
            except Exception as e:
                print(f"    ⚠️  Q{q_plan.number} generation failed: {e} — skipping")
                traceback.print_exc()

        if not questions:
            raise RuntimeError("No questions were generated successfully.")

        meta = {
            "date":        date.today().strftime("%d %B %Y"),
            "board":       board,
            "subject":     subject,
            "paper_title": f"{topic} — Practice Worksheet",
            "tier":        topic,
            "code":        f"Y{year}",
            "time":        f"{len(questions) * 5} minutes (approx.)",
        }

        print(f"\n  📄 Assembling LaTeX project...")
        assemble_latex_project(job_dir, meta, student_name, questions, plan)

        print(f"\n  🔨 Compiling PDF...")
        compiled = compile_with_fix_loop(job_dir, questions)
        pdf_path = job_dir / "main.pdf"

        if not compiled or not pdf_path.exists():
            raise RuntimeError("PDF compilation failed after all retry attempts.")

        mark_scheme = build_mark_scheme(student_name, topic, plan, questions)
        ms_path = job_dir / "mark_scheme.json"
        ms_path.write_text(json.dumps(mark_scheme, indent=2))

        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            safe_name = f"{student_name.replace(' ', '_')}_{topic.replace(' ', '_')}_{job_id}"
            final_pdf = Path(output_dir) / f"{safe_name}.pdf"
            final_ms  = Path(output_dir) / f"{safe_name}_markscheme.json"
            shutil.copy(pdf_path, final_pdf)
            shutil.copy(ms_path, final_ms)
            pdf_path = final_pdf

        print(f"\n  🎉 Worksheet complete!")
        print(f"     PDF:         {pdf_path}")
        print(f"     Questions:   {len(questions)}")
        print(f"     Total marks: {sum(q.marks for q in questions)}")

        return {
            "pdf_path": str(pdf_path), "mark_scheme": mark_scheme,
            "plan": plan.model_dump(), "job_id": job_id,
            "success": True, "error": None,
        }

    except Exception as e:
        print(f"\n  ❌ Worksheet generation failed: {e}")
        traceback.print_exc()
        return {
            "pdf_path": None, "mark_scheme": None, "plan": None,
            "job_id": job_id, "success": False, "error": str(e),
        }


if __name__ == "__main__":
    test_profile = {
        "name": "Ahmed Hassan", "year": 10,
        "curriculum_id": "edexcel_igcse_4ma1_higher",
        "topic_scores": {"Trigonometry": 0.45, "Pythagoras": 0.70},
        "known_misconceptions": [
            "confuses sin and cos when angle is given",
            "forgets to square root at the end of Pythagoras",
        ],
        "error_patterns": [
            "sign errors in final step",
            "does not show sufficient working for method marks",
        ],
        "teacher_notes": "Strong visual learner. Responds well to diagram-based questions.",
    }

    result = generate_worksheet(
        student_profile=test_profile,
        topic="Trigonometry",
        output_dir=Path("output_worksheets"),
    )

    if result["success"]:
        print(f"\n✅ PDF ready: {result['pdf_path']}")
    else:
        print(f"\n❌ Failed: {result['error']}")