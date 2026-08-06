#!/usr/bin/env python3
"""
worksheet_diagram_fixer.py
──────────────────────────
Iterative render → analyse → fix cycle adapted for Cloud LearnX question files.
Uses Gemini Vision for Analysis/Judging and Claude 3.5 Sonnet for LaTeX fixing.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz
import google.generativeai as genai
from anthropic import Anthropic
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not GEMINI_API_KEY or not ANTHROPIC_API_KEY:
    print(
        "[ERROR] Both GEMINI_API_KEY and ANTHROPIC_API_KEY must be set in your .env file."
    )
    sys.exit(1)

genai.configure(api_key=GEMINI_API_KEY)
claude_client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Default to the most capable/affordable models for this specific task
ANALYST_MODEL = os.getenv("ANALYST_MODEL", "gemini-3.1-flash-lite")
FIXER_MODEL = os.getenv("FIXER_MODEL", "claude-haiku-4-5-20251001")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gemini-3.1-flash-lite")

MAX_ITERATIONS = int(os.getenv("MAX_FIX_ITERATIONS", "6"))
RENDER_DPI = int(os.getenv("RENDER_DPI", "200"))
MAX_IMAGE_DIM = int(os.getenv("MAX_IMAGE_DIM", "1400"))


# ── Document wrapper ──────────────────────────────────────────────────────────
QUESTION_DOCUMENT_TEMPLATE = r"""\documentclass[11pt]{article}
INPUT_PACKAGES
INPUT_MACROS

\renewcommand{\familydefault}{\sfdefault}

\newcounter{totalmarks}
\newcounter{questionmarks}
\newcounter{questionNum}

\begin{document}
\newgeometry{left=0.6in, right=0.6in, top=2cm, bottom=2cm}

QUESTION_CONTENT

\end{document}
"""


def find_project_root(start: Path) -> Path:
    p = start
    for _ in range(6):
        if (p / "layout").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return start


def wrap_question_tex(question_tex: str, project_root: Path) -> str:
    packages_path = project_root / "layout" / "packages.tex"
    macros_path = project_root / "layout" / "macros.tex"

    if packages_path.exists():
        pkg_input = f"\\input{{{packages_path}}}"
    else:
        pkg_input = (
            r"\usepackage{tikz}"
            + "\n"
            r"\usetikzlibrary{angles,quotes,calc}"
            + "\n"
            r"\usepackage[a4paper, left=1.2in, right=0.75in, top=1.5cm, bottom=1.5cm]{geometry}"
        )

    macro_input = f"\\input{{{macros_path}}}" if macros_path.exists() else ""

    doc = QUESTION_DOCUMENT_TEMPLATE
    doc = doc.replace("INPUT_PACKAGES", pkg_input)
    doc = doc.replace("INPUT_MACROS", macro_input)
    doc = doc.replace("QUESTION_CONTENT", question_tex)
    return doc


def load_marking_scheme_for_question(
    job_dir: Path, question_num_str: str
) -> dict:
    """
    Attempts to locate mark_scheme.json or marking_scheme.json in the job directory
    and extract the scheme corresponding to this question.
    """
    possible_names = [
        "mark_scheme.json",
        "marking_scheme.json",
        "scheme.json",
    ]
    scheme_file = None

    # Search in job_dir and parent folders
    for name in possible_names:
        candidate = job_dir / name
        if candidate.exists():
            scheme_file = candidate
            break
        candidate_parent = job_dir.parent / name
        if candidate_parent.exists():
            scheme_file = candidate_parent
            break

    if not scheme_file:
        return {}

    try:
        with open(scheme_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Normalize q_num key (e.g., "q1.tex" -> "q1" or 1)
        q_key = question_num_str.lower().replace(".tex", "")

        if isinstance(data, dict):
            if q_key in data:
                return data[q_key]
            # Try numeric key
            num_match = re.search(r"\d+", q_key)
            if num_match and num_match.group(0) in data:
                return data[num_match.group(0)]
            if num_match and int(num_match.group(0)) in data:
                return data[int(num_match.group(0))]
            # Fall back to entire json if small
            return data
    except Exception as e:
        print(f"  [WARN] Failed to read scheme file {scheme_file}: {e}")

    return {}


# ── Rendering & Image Prep ────────────────────────────────────────────────────
def render_tex_to_pdf(tex_source: str, work_dir: Path) -> Path:
    # Ensure the target directory exists before writing to it
    work_dir.mkdir(parents=True, exist_ok=True)
    
    tex_path = work_dir / "input.tex"
    tex_path.write_text(tex_source, encoding="utf-8")

    result = subprocess.run(
        [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory",
            str(work_dir),
            str(tex_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    pdf_path = work_dir / "input.pdf"
    if not pdf_path.exists():
        raise RuntimeError(
            f"pdflatex failed:\n{result.stdout[-1000:]}\n{result.stderr[-500:]}"
        )
    return pdf_path


def pdf_to_png(pdf_path: Path, output_png_path: Path, dpi: int = RENDER_DPI) -> Path:
    """Explicitly saves to output_png_path instead of implicitly overwriting input.png"""
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    pix.save(str(output_png_path))
    doc.close()
    return output_png_path

def get_resized_image(
    png_path: Path, max_dim: int = MAX_IMAGE_DIM
) -> Image.Image:
    img = Image.open(png_path)
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    return img


# ── Agent prompts ─────────────────────────────────────────────────────────────
ANALYST_PROMPT = """\
You are a specialist reviewer of mathematics exam worksheet diagrams — specifically
TikZ diagrams used in IGCSE/GCSE-style question papers. You ONLY describe defects.
You NEVER suggest fixes or produce corrected code.

COMMON DEFECTS IN MATH EXAM DIAGRAMS (check all of these):

1. REFLEX ARC ERROR — The \\pic{angle = A--V--B} macro draws angles counter-clockwise.
   Assess correct usage of sweep direction with reference to intent from marking scheme.

2. COORDINATE/PROPORTION MISMATCH — If a triangle side is labelled "15.6m" but
   visually appears shorter than a side labelled "7.2m", the coordinates don't
   match the stated measurements. REPORT which sides are wrongly proportioned.

3. TRIVIAL / REVEALED ANSWER — If a diagram marks a variable x° where the angle
   is visually obvious (e.g. clearly 90°, or clearly equal to a labelled angle),
   the question is trivialised. REPORT if x° appears to reveal the answer.

4. FLOATING / DISCONNECTED LABELS — Node labels that appear far from their
   intended anchor geometry. REPORT which label and where it should be.

5. OFF-GRID / CLIPPED SHAPES — For transformation/grid questions, check if any
   shape vertex is clipped outside the grid boundary. REPORT any clipped vertices.
   For questions that require students to draw transformed shape ensure the answer
   coordinates are within bounds -- refer to the marking scheme for the expected answer coordinates.

6. INCONSISTENT SCALE — Diagrams that are compressed, distorted, or have
   elements overlapping the question text. REPORT any layout issues.

7. WRONG ANGLE DIRECTION — Right-angle marks drawn in the wrong corner.
   REPORT if a right-angle mark is at the wrong vertex.

8. PARTIALLY DRAWN ARCS - Arcs sweeping more than or less than the intended angle. Arcs should 
    always be between two lines and not extend beyond them. Such arcs may reveal an underlying error in
    the diagram. Report this accurately after refering to marking scheme.

9. ACCURATE ANGLE CLASSIFICATION: Diagrams must maintain visual accuracy: acute, obtuse, and 
    reflex angles must clearly reflect their geometric classifications. 

Response format when defects exist:
---DEFECTS---
1. [CRITICAL/MODERATE/MINOR] <precise description — which element, what's wrong>
---END---
"""

FIXER_PROMPT = """\
You are a LaTeX/TikZ specialist fixing mathematics exam worksheet diagrams.

You will receive:
1. A defect report describing exactly what is visually wrong
2. The current TikZ source code
3. The macro system context (answerplain, answereq, etc.)

CRITICAL RULES FOR MATH EXAM DIAGRAMS:

ANGLE ARCS:
  \\pic{angle = A--V--B} draws counter-clockwise from A to B around V.
  To fix a reflex arc: REVERSE the point order in the angle spec.
  Wrong: {angle = A--B--C}  →  Fix: {angle = C--B--A}

COORDINATE PROPORTIONALITY:
  If side AB is stated as 7.2m and side BC as 15.6m, then in tikz coordinates
  BC must appear longer than AB in the SAME ratio.
  Recompute coordinates from stated measurements before placing nodes.

GRID BOUNDS:
  If transformation shapes fall outside grid limits, adjust EITHER:
  - The original shape position, OR
  - The centre/axis of transformation
  until ALL image vertices fall strictly within the grid.

TRIVIAL/ REVEALED ANSWER:
  If a particular label is identified to reveal or trivializes the probem
  the element must be removed entirely.
  ex: 

LABEL PLACEMENT:
  Use [above], [below], [left], [right], [above left] etc. anchored to geometry.
  Never place labels at arbitrary floating coordinates.

OUTPUT INSTRUCTIONS:
  - Return ONLY the corrected LaTeX content between \\begin{question} and \\end{question}
  - Do NOT include \\documentclass, preamble, or explanations
  - Do NOT change the mathematical content of the question — only fix the diagram
  - Do NOT modify answer macros (\\answerplain, \\answereq, etc.)

If you cannot fix the diagram without breaking the question, state:
CANNOT_FIX: <reason>
"""

JUDGE_PROMPT = """\
You are a quality judge for mathematics exam worksheet diagrams.
You compare a BEFORE and AFTER version of a diagram and decide if the patch fixed the specific defect.

Target Defect to Evaluate:
{defects}

Rules for Judging:
1. Focus strictly on whether the TARGET DEFECT listed above is resolved in the AFTER (second) image.
2. If the arc, label, or coordinate error from the target defect was fixed in the AFTER image, accept the fix! Do not mark it UNCHANGED or DEGRADED if the specific issue was corrected.
3. Ignore subtle font shifts or identical text alignment if the target diagram bug was solved.

Verdicts:
  IMPROVED: The target defect was successfully resolved.
  PERFECT:  The target defect was resolved and the entire diagram looks production-ready.
  DEGRADED: The fix made the target defect worse or broke another major part of the layout.
  UNCHANGED: The AFTER image is completely identical to the BEFORE image and the target defect remains totally unfixed.

Respond in this exact format:
VERDICT: <IMPROVED|DEGRADED|PERFECT|UNCHANGED>
REASON: <one sentence>
"""


# ── Agents ────────────────────────────────────────────────────────────────────
def run_analyst(
    image_path: Path,
    current_tex: str,
    iteration: int = 1,
    hints: str = "",
    scheme_data: dict = None,
) -> dict:
    scheme_str = (
        f"\n\n=== MARKING SCHEME / GROUND TRUTH CONTEXT ===\n{json.dumps(scheme_data, indent=2)}\n"
        if scheme_data
        else ""
    )

    prompt = (
        f"{ANALYST_PROMPT}\n\n"
        f"Iteration {iteration}. Analyse this mathematics exam diagram for defects.\n\n"
        f"TeX source:\n```latex\n{current_tex}\n```"
        f"{scheme_str}"
        + (f"\n\nHints: {hints}" if hints else "")
    )

    img = get_resized_image(image_path)
    model = genai.GenerativeModel(ANALYST_MODEL)

    resp = model.generate_content([prompt, img])
    text = (resp.text or "").strip()

    if "DIAGRAM_OK" in text:
        return {"ok": True, "defects": ""}

    m = re.search(r"---DEFECTS---\s*\n(.*?)---END---", text, re.DOTALL)
    defects = m.group(1).strip() if m else text
    return {"ok": False, "defects": defects}


def run_fixer(
    defects: str,
    current_tex: str,
    iteration: int = 1,
    history: str = "",
    hints: str = "",
) -> dict:
    user_msg = (
        f"Defect report (iteration {iteration}):\n{defects}\n\n"
        + (f"Fix history:\n{history}\n\n" if history else "")
        + (f"Hints: {hints}\n\n" if hints else "")
        + f"Current TeX:\n```latex\n{current_tex}\n```\n\n"
        "Produce the corrected TeX content only."
    )

    resp = claude_client.messages.create(
        model=FIXER_MODEL,
        system=FIXER_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=4000,
        temperature=0.1,
    )

    text = (resp.content[0].text or "").strip()

    if text.startswith("CANNOT_FIX"):
        print(f"  [FIXER] Cannot fix: {text}")
        return {"fixed_tex": None}

    m = re.search(r"(\\begin\{question\}.*?\\end\{question\})", text, re.DOTALL)
    if m:
        return {"fixed_tex": m.group(1).strip()}

    text = re.sub(r"^```(?:latex)?\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return {"fixed_tex": text.strip() if text.strip() else None}


def run_judge(before_path: Path, after_path: Path, defects: str) -> dict:
    judge_prompt_formatted = JUDGE_PROMPT.format(defects=defects)
    prompt = (
        f"{judge_prompt_formatted}\n\n"
        "Compare BEFORE (first image) and AFTER (second image) diagrams."
    )

    img_before = get_resized_image(before_path, max_dim=900)
    img_after = get_resized_image(after_path, max_dim=900)

    model = genai.GenerativeModel(JUDGE_MODEL)
    resp = model.generate_content([prompt, img_before, img_after])
    text = (resp.text or "").strip()

    m_v = re.search(r"VERDICT:\s*(\w+)", text, re.IGNORECASE)
    verdict = m_v.group(1).upper() if m_v else "UNCHANGED"

    is_improved = verdict in ("IMPROVED", "PERFECT", "ACCEPT", "ACCEPTED")
    is_perfect = verdict in ("PERFECT",)

    return {
        "verdict": verdict,
        "perfect": is_perfect,
        "improved": is_improved,
        "text": text,
    }


# ── Per-question fix loop ─────────────────────────────────────────────────────
def fix_question_file(
    question_tex_path: Path,
    project_root: Path,
    output_dir: Path,
    hints: str = "",
    max_iterations: int = MAX_ITERATIONS,
    job_dir: Path = None,
) -> bool:
    q_name = question_tex_path.stem
    q_out = output_dir / q_name
    q_out.mkdir(parents=True, exist_ok=True)

    # Load marking scheme if present
    scheme_data = {}
    if job_dir:
        scheme_data = load_marking_scheme_for_question(job_dir, q_name)
        if scheme_data:
            print(f"  [INFO] Attached ground-truth marking scheme for {q_name}")

    # CREATE A SAFE BACKUP BEFORE WE DO ANYTHING
    backup_path = question_tex_path.with_suffix(".tex.bak")
    if not backup_path.exists():
        shutil.copy2(question_tex_path, backup_path)

    current_tex = question_tex_path.read_text(encoding="utf-8")
    best_tex = current_tex
    history = []
    consecutive_rejects = 0

    print(f"\n{'='*60}")
    print(f"  Fixing: {question_tex_path.name}")
    print(f"  Output: {q_out}")
    print(f"{'='*60}")

    for iteration in range(1, max_iterations + 1):
        print(f"\n  ── Iteration {iteration}/{max_iterations} ──")

        with tempfile.TemporaryDirectory(prefix="wsfix_") as tmp:
            work = Path(tmp)

            # 1. Compile BEFORE state
            try:
                full_doc = wrap_question_tex(current_tex, project_root)
                build_before = work / "before_build"
                build_before.mkdir(parents=True, exist_ok=True)  # <-- CREATE DIRECTORY
                
                pdf_before = render_tex_to_pdf(full_doc, build_before)
                before_png = work / "before.png"
                pdf_to_png(pdf_before, before_png)
            except RuntimeError as e:
                print(f"  [RENDER ERROR] {str(e)[:300]}")
                print("  Cannot render — skipping this question.")
                return False

            snap_png = q_out / f"iter_{iteration:02d}_before.png"
            snap_tex = q_out / f"iter_{iteration:02d}_before.tex"
            shutil.copy2(before_png, snap_png)
            snap_tex.write_text(current_tex, encoding="utf-8")

            print(f"  [ANALYST] Analysing...")
            analyst = run_analyst(
                before_png,
                current_tex,
                iteration=iteration,
                hints=hints,
                scheme_data=scheme_data,
            )

            if analyst["ok"]:
                print(f"  ✅ DIAGRAM_OK — no defects at iteration {iteration}")
                (q_out / "final.tex").write_text(current_tex, encoding="utf-8")
                shutil.copy2(snap_png, q_out / "final.png")
                question_tex_path.write_text(current_tex, encoding="utf-8")
                print(f"  ✅ Written back to {question_tex_path}")
                return True

            defects = analyst["defects"]
            print(f"  [ANALYST] Defects:\n{defects[:400]}")
            history.append(f"Iter {iteration}: {defects[:150]}")

            print(f"  [FIXER] Generating fix...")
            fixer = run_fixer(
                defects,
                current_tex,
                iteration=iteration,
                history="\n".join(history),
                hints=hints,
            )

            if fixer["fixed_tex"] is None:
                print("  [FIXER] No fix produced — skipping iteration.")
                continue

            proposed_tex = fixer["fixed_tex"]

            # 2. Compile AFTER state in a SEPARATE directory / path
            try:
                proposed_doc = wrap_question_tex(proposed_tex, project_root)
                pdf_after = render_tex_to_pdf(proposed_doc, work / "after_build")
                after_png = work / "after.png"
                pdf_to_png(pdf_after, after_png)
            except RuntimeError as e:
                print(f"  [FIXER RENDER ERROR] Fix failed to compile: {str(e)[:200]}")
                consecutive_rejects += 1
                continue

            after_snap = q_out / f"iter_{iteration:02d}_after.png"
            shutil.copy2(after_png, after_snap)

            # 3. Judge now compares TWO TRULY DIFFERENT PNG FILES!
            print(f"  [JUDGE] Evaluating...")
            judge = run_judge(before_png, after_png, defects)
            print(f"  [JUDGE] {judge['verdict']} — {judge['text'][:100]}")

            if judge["perfect"]:
                print(f"  ✅ PERFECT — accepting and writing back")
                current_tex = proposed_tex
                (q_out / "final.tex").write_text(current_tex, encoding="utf-8")
                shutil.copy2(after_snap, q_out / "final.png")
                question_tex_path.write_text(current_tex, encoding="utf-8")
                print(f"  ✅ Written back to {question_tex_path}")
                return True

            if judge["improved"]:
                current_tex = proposed_tex
                best_tex = proposed_tex
                consecutive_rejects = 0
                print(f"  ✓ IMPROVED — accepted, continuing...")
            else:
                consecutive_rejects += 1
                print(f"  ✗ REJECTED — reverting")
                history.append(f"Iter {iteration} fix rejected by judge")
                if consecutive_rejects >= 2:
                    print(
                        f"  [WARN] 2 consecutive rejections — resetting to best version"
                    )
                    current_tex = best_tex
                    consecutive_rejects = 0

    print(f"\n  ⚠️  Max iterations reached — saving best version")
    (q_out / "final.tex").write_text(best_tex, encoding="utf-8")
    question_tex_path.write_text(best_tex, encoding="utf-8")
    return False


def has_diagram(tex_path: Path) -> bool:
    content = tex_path.read_text(encoding="utf-8", errors="ignore")
    return "tikzpicture" in content or "\\begin{tikzpicture}" in content


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Fix diagram defects in worksheet question .tex files"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--job",
        help="Path to a worksheet job folder (e.g. worksheet_jobs/96b32e9a)",
    )
    group.add_argument("--file", help="Path to a single question .tex file")

    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output directory for fix artefacts",
    )
    parser.add_argument(
        "--hints", "-H", default="", help="Optional hints for the fixer"
    )
    parser.add_argument(
        "--max-iter",
        type=int,
        default=MAX_ITERATIONS,
        help=f"Max iterations (default: {MAX_ITERATIONS})",
    )
    parser.add_argument(
        "--all", action="store_true", help="Process ALL question files"
    )
    args = parser.parse_args()

    if args.file:
        tex_path = Path(args.file).resolve()
        project_root = find_project_root(tex_path)
        job_dir = tex_path.parent.parent
        out_dir = (
            Path(args.output)
            if args.output
            else tex_path.parent.parent / "diagram_fixes"
        )
        fix_question_file(
            tex_path,
            project_root,
            out_dir,
            args.hints,
            args.max_iter,
            job_dir=job_dir,
        )
    else:
        job_dir = Path(args.job).resolve()
        questions_dir = job_dir / "questions"

        if not questions_dir.exists():
            print(f"[ERROR] No questions/ folder found in {job_dir}")
            sys.exit(1)

        project_root = find_project_root(job_dir)
        out_dir = (
            Path(args.output) if args.output else job_dir / "diagram_fixes"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        tex_files = sorted(questions_dir.glob("q*.tex"))
        if not tex_files:
            print(f"[ERROR] No q*.tex files found in {questions_dir}")
            sys.exit(1)

        targets = (
            tex_files if args.all else [f for f in tex_files if has_diagram(f)]
        )

        print(
            f"Found {len(tex_files)} question files, {len(targets)} have diagrams"
        )
        print(
            f"Models: Analyst={ANALYST_MODEL}  Fixer={FIXER_MODEL}  Judge={JUDGE_MODEL}"
        )

        results = {}
        for tex_path in targets:
            ok = fix_question_file(
                tex_path,
                project_root,
                out_dir,
                args.hints,
                args.max_iter,
                job_dir=job_dir,
            )
            results[tex_path.name] = "✅ fixed" if ok else "⚠️  max iters"

        print(f"\n{'='*60}")
        print(f"  SUMMARY")
        print(f"{'='*60}")
        for name, status in results.items():
            print(f"  {name}: {status}")


if __name__ == "__main__":
    main()