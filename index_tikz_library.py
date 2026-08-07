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
    Extract each \begin{tikzpicture}...\end{tikzpicture} block separately.
    Discards non-TikZ question wrappers (e.g., \begin{question}).
    """
    blocks = re.findall(r'\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}', content, re.DOTALL)
    return blocks  # Returns empty list if no valid tikzpicture environment exists


for tex_file in TIKZ_DIR.glob("*.tex"):
    content  = tex_file.read_text()
    diagrams = split_into_diagrams(content)

    if not diagrams:
        print(f"⚠️  Skipping {tex_file.name} — no \\begin{{tikzpicture}} block found.")
        continue

    if len(diagrams) > 1:
        print(f"📄 {tex_file.stem} — {len(diagrams)} diagrams found, indexing separately")

    for i, diagram_tex in enumerate(diagrams, start=1):
        diagram_name = f"{tex_file.stem}_{i}"

        # Skip if already indexed
        existing = supabase.table("tikz_library").select("id").eq("filename", diagram_name).execute()
        if existing.data:
            print(f"⏭️  Skipping {diagram_name} — already indexed")
            continue

        # Generate a descriptive mathematical summary for vector search
        desc_prompt = (
            "Analyze this TikZ code and give a clear 1-sentence description of the mathematical diagram "
            "it represents (include topic/key geometry features, e.g., 'Right-angled triangle with hypotenuse labeling' "
            "or 'Circle theorem showing central angle and inscribed angle' or 'Circle theorem with intersecting tangents'):\n\n"
            f"{diagram_tex}"
        )
        desc_response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=desc_prompt
        )
        description = desc_response.text.strip()

        # Generate embedding with RETRIEVAL_DOCUMENT task type
        embed_response = client.models.embed_content(
            model="gemini-embedding-001",
            contents=f"{diagram_name}: {description}\n\n{diagram_tex}",
            config=types.EmbedContentConfig(
                output_dimensionality=768,
                task_type="RETRIEVAL_DOCUMENT"
            )
        )
        embedding = embed_response.embeddings[0].values

        # Store in Supabase
        supabase.table("tikz_library").insert({
            "filename":    diagram_name,
            "description": description,
            "tex_content": diagram_tex,
            "embedding":   embedding,
        }).execute()

        print(f"✅ Indexed: {diagram_name} — {description}")

print("Done — tikz library indexed.")