"""
claude_client.py
──────────────────
Shared Anthropic API helpers for the worksheet generator:
  - Structured output via forced tool-use (Pydantic model → tool schema)
  - Prompt caching for static context blocks (macros, sample questions)
  - Retry logic with exponential backoff
"""

import os
import re
import time
import anthropic
from pydantic import BaseModel
from typing import Type, TypeVar
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

# ── Models ────────────────────────────────────────────────────────────────────
MODEL_SONNET = "claude-sonnet-5"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

T = TypeVar("T", bound=BaseModel)


# ── Retry wrapper ─────────────────────────────────────────────────────────────
def call_with_retry(fn, retries: int = 4, base_delay: float = 15.0):
    """Exponential backoff retry — mirrors pipeline.py's pattern."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            err_str = str(e).lower()
            is_rate_limit   = "429" in err_str or "rate_limit" in err_str or "overloaded" in err_str
            is_server_error = "500" in err_str or "503" in err_str or "529" in err_str

            if attempt == retries - 1:
                raise

            if is_rate_limit or is_server_error:
                match = re.search(r"retry[^\d]*(\d+)", str(e), re.IGNORECASE)
                wait  = (int(match.group(1)) + 5) if match else base_delay * (2 ** attempt)
                print(f"  ⏳ Retry {attempt+1}/{retries} — waiting {wait:.0f}s...")
                time.sleep(wait)
            else:
                raise


# ── Structured output via forced tool-use ─────────────────────────────────────
def pydantic_to_tool_schema(model: Type[BaseModel], tool_name: str) -> dict:
    """Convert a Pydantic model into an Anthropic tool definition."""
    schema = model.model_json_schema()
    return {
        "name": tool_name,
        "description": f"Return data matching the {tool_name} schema. Always call this tool with complete, valid data.",
        "input_schema": schema,
    }


def generate_structured(
    system_blocks: list,
    user_message:  str,
    output_model:  Type[T],
    tool_name:     str,
    model:         str   = MODEL_SONNET,
    max_tokens:    int   = 4096,
    temperature:   float = 0.4,
) -> T:
    """
    Calls Claude with forced tool-use to get reliable structured JSON output,
    validated against a Pydantic model.
    """
    tool = pydantic_to_tool_schema(output_model, tool_name)

    def _call():
        return client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_blocks,
            messages=[{"role": "user", "content": user_message}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name},
        )

    response = call_with_retry(_call)

    # Log token usage so you can track costs and cache hit rates
    usage = response.usage
    cache_read    = getattr(usage, "cache_read_input_tokens", 0)
    cache_created = getattr(usage, "cache_creation_input_tokens", 0)
    print(f"    [tokens] in={usage.input_tokens} out={usage.output_tokens}"
          + (f" cache_read={cache_read}" if cache_read else "")
          + (f" cache_write={cache_created}" if cache_created else ""))

    for block in response.content:
        if block.type == "tool_use":
            return output_model.model_validate(block.input)

    raise RuntimeError(f"No tool_use block returned for {tool_name}")


def generate_text(
    system_blocks: list,
    user_message:  str,
    model:         str   = MODEL_SONNET,
    max_tokens:    int   = 4096,
    temperature:   float = 0.2,
) -> str:
    """Plain text generation — used for LaTeX fix-up, no structured schema needed."""
    def _call():
        return client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_blocks,
            messages=[{"role": "user", "content": user_message}],
        )

    response = call_with_retry(_call)
    return "".join(b.text for b in response.content if b.type == "text").strip()


# ── Cache-control helpers ──────────────────────────────────────────────────────
def cached_block(text: str) -> dict:
    """Wrap a text block with an ephemeral cache breakpoint (5 min TTL)."""
    return {
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"}
    }


def plain_block(text: str) -> dict:
    """Plain text block — not cached."""
    return {"type": "text", "text": text}