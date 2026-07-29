# index_tikz_library.py
import os
import re
from pathlib import Path
from google import genai
from google.genai import types
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

client   = genai.Client()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

TIKZ_DIR = Path("tikz_samples")


def split_into_diagrams(content: str):
    """
    Extract each \\begin{tikzpicture}...\\end{tikzpicture} block separately.
    Falls back to treating the whole file as one block if no tikzpicture
    environment is found (e.g. a file using a different drawing method).
    """
    blocks = re.findall(r'\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}', content, re.DOTALL)
    return blocks if blocks else [content]


for tex_file in TIKZ_DIR.glob("*.tex"):
    content  = tex_file.read_text()
    diagrams = split_into_diagrams(content)

    if len(diagrams) > 1:
        print(f"📄 {tex_file.stem} — {len(diagrams)} diagrams found, indexing separately")

    for i, diagram_tex in enumerate(diagrams, start=1):
        # Give each diagram a unique name — e.g. "2d_shapes_1", "2d_shapes_2"
        # Single-diagram files just get "_1" appended, which is fine.
        diagram_name = f"{tex_file.stem}_{i}"

        # Skip if already indexed — makes it safe to re-run after a crash
        existing = supabase.table("tikz_library").select("id").eq("filename", diagram_name).execute()
        if existing.data:
            print(f"⏭️  Skipping {diagram_name} — already indexed")
            continue

        # Ask Gemini to describe THIS specific diagram, not the whole file
        desc_response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=f"In one sentence, describe what mathematical diagram this tikz code draws:\n{diagram_tex}"
        )
        description = desc_response.text.strip()

        # Generate embedding from the description + name
        # gemini-embedding-001 replaces the deprecated text-embedding-004
        embed_response = client.models.embed_content(
            model="gemini-embedding-001",
            contents=f"{diagram_name}: {description}",
            config=types.EmbedContentConfig(output_dimensionality=768)
        )
        embedding = embed_response.embeddings[0].values

        # Store in Supabase — one row per diagram, not per file
        supabase.table("tikz_library").insert({
            "filename":    diagram_name,
            "description": description,
            "tex_content": diagram_tex,
            "embedding":   embedding,
        }).execute()

        print(f"✅ Indexed: {diagram_name} — {description}")

print("Done — tikz library indexed.")