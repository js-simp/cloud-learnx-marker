"""
ingest_error_examples.py
──────────────────────────
One-off / re-runnable script to load your reviewed q{n}/q{n}_fixed/q{n}_notes
triples into the error_examples Supabase table for RAG retrieval during
generation.

USAGE:
    python ingest_error_examples.py --dir /path/to/error_examples_folder

Expects a FLAT folder containing, for each reviewed question number N:
    q{N}.tex          — the original flawed question (the "error" version)
    q{N}_fixed.tex     — the corrected version
    q{N}_notes.md      — review notes in the exact format produced by the
                         tex_reviewer tool:

        # Q{N} — Review Notes

        ## Error classes identified
        - TAXONOMY TAG ONE
        - TAXONOMY TAG TWO

        ## Explanation of errors and fixes
        Free text explanation...

Re-running this script is safe — it upserts on source_number, so fixing a
notes.md typo and re-running won't create duplicates.
"""

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from supabase import create_client

load_dotenv()

EMBED_MODEL      = "gemini-embedding-001"
EMBED_DIMENSIONS = 768

_gemini_client   = genai.Client()
_supabase_client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


def parse_notes_md(text: str) -> tuple[list[str], str]:
    """
    Parses the tex_reviewer's notes.md format:
        ## Error classes identified
        - TAG ONE
        - TAG TWO

        ## Explanation of errors and fixes
        <free text>

    Returns (error_classes, explanation).
    """
    error_classes = []
    tags_match = re.search(
        r"## Error classes identified\s*\n(.*?)(?=\n##|\Z)", text, re.DOTALL
    )
    if tags_match:
        for line in tags_match.group(1).splitlines():
            line = line.strip().lstrip("-").strip()
            if line and line != "(none selected)":
                error_classes.append(line)

    explanation = ""
    exp_match = re.search(
        r"## Explanation of errors and fixes\s*\n(.*)", text, re.DOTALL
    )
    if exp_match:
        explanation = exp_match.group(1).strip()
        explanation = re.sub(r"^_\(no explanation provided\)_$", "", explanation).strip()

    return error_classes, explanation


def find_triples(dir_path: Path) -> list[dict]:
    """
    Scans a flat directory for q{N}.tex / q{N}_fixed.tex / q{N}_notes.md
    triples. Skips any number missing one of the three files, with a warning.
    """
    # Match q{N}.tex but NOT q{N}_fixed.tex / q{N}_notes.md
    error_files = sorted(
        f for f in dir_path.glob("q*.tex")
        if not f.stem.endswith("_fixed")
    )

    triples = []
    for error_file in error_files:
        m = re.match(r"^q(\w+)\.tex$", error_file.name)
        if not m:
            continue
        num = m.group(1)

        fixed_file = dir_path / f"q{num}_fixed.tex"
        notes_file = dir_path / f"q{num}_notes.md"

        missing = [f.name for f in (fixed_file, notes_file) if not f.exists()]
        if missing:
            print(f"  ⚠️  Skipping q{num} — missing: {', '.join(missing)}")
            continue

        triples.append({
            "source_number": num,
            "error_tex":     error_file.read_text(),
            "fixed_tex":     fixed_file.read_text(),
            "notes_raw":     notes_file.read_text(),
        })

    return triples


def build_embedding_source(error_classes: list[str], explanation: str, topic: str = "") -> str:
    """
    Builds the text that actually gets embedded. Deliberately NOT the raw
    LaTeX — tex syntax (braces, backslashes, tikz coordinates) is noise for
    semantic matching. What we want to match against is: what kind of
    mistake was this, described in the same terms a new q_plan's
    topic/topic_aspect would use.
    """
    parts = []
    if topic:
        parts.append(f"Topic: {topic}")
    parts.append(f"Error classes: {', '.join(error_classes)}")
    parts.append(f"Explanation: {explanation}")
    return "\n".join(parts)


def embed_text(text: str) -> list[float]:
    response = _gemini_client.models.embed_content(
        model=EMBED_MODEL,
        contents=text,
        config=genai_types.EmbedContentConfig(
            output_dimensionality=EMBED_DIMENSIONS,
            task_type="RETRIEVAL_DOCUMENT",  # document-side embedding, matching query-side RETRIEVAL_QUERY at retrieval time
        ),
    )
    return response.embeddings[0].values


def main():
    parser = argparse.ArgumentParser(description="Ingest reviewed error/fixed pairs into Supabase")
    parser.add_argument("--dir", required=True, help="Flat folder containing q{N}.tex / q{N}_fixed.tex / q{N}_notes.md")
    parser.add_argument("--topic", default="", help="Optional topic label to attach to every entry in this batch (e.g. 'Circle Theorems'). Leave blank if your folder spans multiple topics — see --topic-per-file below.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print what would be ingested, without calling the embedding API or writing to Supabase")
    args = parser.parse_args()

    dir_path = Path(args.dir).resolve()
    if not dir_path.exists():
        sys.exit(f"Directory does not exist: {dir_path}")

    triples = find_triples(dir_path)
    print(f"Found {len(triples)} complete triples in {dir_path}\n")

    if not triples:
        sys.exit("Nothing to ingest.")

    succeeded, failed = 0, 0

    for t in triples:
        num = t["source_number"]
        error_classes, explanation = parse_notes_md(t["notes_raw"])

        if not error_classes:
            print(f"  ⚠️  q{num}: no error classes parsed from notes.md — skipping")
            failed += 1
            continue
        if not explanation:
            print(f"  ⚠️  q{num}: no explanation parsed from notes.md — skipping")
            failed += 1
            continue

        embedding_source = build_embedding_source(error_classes, explanation, args.topic)

        print(f"  → q{num}: {error_classes}")
        if args.dry_run:
            print(f"      embedding_source: {embedding_source!r}")
            succeeded += 1
            continue

        try:
            embedding = embed_text(embedding_source)
        except Exception as e:
            print(f"  ⚠️  q{num}: embedding failed — {e}")
            failed += 1
            continue

        try:
            _supabase_client.table("error_examples").upsert({
                "source_number":    num,
                "topic":            args.topic or None,
                "error_classes":    error_classes,
                "error_tex":        t["error_tex"],
                "fixed_tex":        t["fixed_tex"],
                "explanation":      explanation,
                "embedding_source": embedding_source,
                "embedding":        embedding,
            }, on_conflict="source_number").execute()
            succeeded += 1
        except Exception as e:
            print(f"  ⚠️  q{num}: Supabase upsert failed — {e}")
            failed += 1

    print(f"\nDone. {succeeded} ingested, {failed} skipped/failed.")


if __name__ == "__main__":
    main()
