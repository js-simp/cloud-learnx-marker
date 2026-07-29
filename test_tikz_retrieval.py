# test_tikz_retrieval.py
# Quick sanity check — search the tikz library and see what comes back

import os
from google import genai
from google.genai import types
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

client   = genai.Client()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


def search_tikz(query: str, n: int = 5):
    # Embed the search query
    embed_response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=query,
        config=types.EmbedContentConfig(output_dimensionality=768)
    )
    query_embedding = embed_response.embeddings[0].values

    # Call the Postgres function for vector similarity search
    results = supabase.rpc("match_tikz_library", {
        "query_embedding": query_embedding,
        "match_count": n
    }).execute()

    print(f"\n🔍 Query: \"{query}\"")
    print(f"{'─'*60}")
    for r in results.data:
        print(f"  [{r['similarity']:.3f}] {r['filename']} — {r['description']}")


if __name__ == "__main__":
    # Try a few different queries to sanity-check retrieval quality
    search_tikz("right angled triangle with sides labelled")
    search_tikz("sine rule finding a missing side")
    search_tikz("circle with an inscribed angle")
    search_tikz("bearings and compass directions")