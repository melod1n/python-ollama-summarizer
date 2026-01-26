import json
import re
from typing import Any

import anyio
import requests

from app.core.config import MODEL_NAME, OLLAMA_API_URL
from app.core.log import log

_SESSION = requests.Session()

# connect timeout, read timeout
_DEFAULT_TIMEOUT = (10, 600)

_JSON_BLOCK_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def _extract_json_block(text: str) -> str:
    """Extract first JSON object/array from text; also removes ```json fences if present."""
    s = (text or "").strip()

    # Remove fenced code blocks if present
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
        s = s.strip()

    m = _JSON_BLOCK_RE.search(s)
    return (m.group(1) if m else s).strip()


def call_ollama(prompt: str, model: str | None) -> str:
    payload = {"model": model or MODEL_NAME, "prompt": prompt, "stream": False}

    try:
        resp = _SESSION.post(OLLAMA_API_URL, json=payload, timeout=_DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.exception(f"❌ Ollama request failed: {e}")
        raise
    except ValueError:
        # response wasn't JSON
        log.error(f"❌ Ollama returned non-JSON response: {resp.text[:500]}")
        raise

    out = data.get("response")
    if not isinstance(out, str):
        raise RuntimeError(f"Unexpected Ollama response shape: {data!r}")

    return out.strip()


async def call_ollama_async(prompt: str) -> str:
    """Async-friendly wrapper (runs blocking requests in a thread)."""
    return await anyio.to_thread.run_sync(call_ollama, prompt)


def build_prompt(text: str) -> str:
    return f"""You are a text analyzer.

Given the following raw HTML of an article:
1. Write a **concise topic-style summary** in **one English sentence** that reflects the article's subject.
   - Do **not** start with phrases like "This article discusses..." or "The article explains...".
   - Make it a **clear, compact statement** of the main idea.
   - Example: "Best practices for handling display cutouts in Android edge-to-edge layouts."
2. Generate **5 to 10 general-topic tags**, written in **English**, lowercase, and **hyphenated** (e.g. "android", "mobile-development", "user-interface").
   - Tags must describe the **overall subject area**, not specific technologies or methods.
   - Avoid concrete APIs or libraries (e.g. no "recyclerview", "compose").
   - Prefer broad tags like "android", "mobile-ui", "design-principles", "user-experience".

Return the result only as valid JSON object, without wrapping it in markdown, code block, or any additional formatting. Just plain JSON. Like this:
{{
  "summary": "...",
  "tags": ["...", "..."]
}}

Here is the HTML:
{text}
"""


def _normalize_tag(tag: str) -> str:
    t = (tag or "").strip().lower()
    t = re.sub(r"\s+", "-", t)
    t = re.sub(r"[^a-z0-9\-]", "", t)
    t = re.sub(r"-{2,}", "-", t).strip("-")
    return t


def filter_tags_via_llm(tag_lists: list[list[str]]) -> list[str]:
    flat = [_normalize_tag(t) for tags in tag_lists for t in tags]
    flat = [t for t in flat if t]
    unique_tags = sorted(set(flat))

    prompt = f"""You are a text categorization assistant.

Here is a list of tags extracted from different parts of an article. They may contain duplicates, synonyms, or overly specific variations.

Your task is to:
- return **no more than 10** general-topic tags.
- remove tags that are too specific or repetitive in meaning.
- prefer broad, meaningful categories over concrete tools or libraries.
- keep the tags **in lowercase** and **hyphenated** (e.g. "machine-learning", "language-models").

Tags:
{json.dumps(unique_tags, indent=2)}

Return the result as a valid JSON array, like this:
["tag-one", "tag-two", "tag-three"]
"""

    raw_text = call_ollama(prompt)
    extracted = _extract_json_block(raw_text)

    try:
        parsed: Any = json.loads(extracted)

        # Sometimes models return {"tags": [...]}
        if isinstance(parsed, dict) and "tags" in parsed:
            parsed = parsed["tags"]

        if isinstance(parsed, list):
            cleaned = [_normalize_tag(t) for t in parsed if isinstance(t, str)]
            cleaned = [t for t in cleaned if t]
            return cleaned[:10] if cleaned else unique_tags[:10]

    except Exception as e:
        log.warning(f"⚠️ Failed to parse tag response from LLM: {e}\nRaw: {raw_text[:800]}")

    return unique_tags[:10]
