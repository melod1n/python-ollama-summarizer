import asyncio
import json
import re
from time import time

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException
from readability import Document
from sqlalchemy import select

from app.core.config import MAX_TOKENS, CHUNK_MAX_TOKENS, CHUNK_OVERLAP
from app.core.log import log
from app.core.runtime import encoding, task_status, queue_lock, task_queue

from app.db.models import Summary
from app.services.chunking import chunk_text
from app.services.ollama import call_ollama, build_prompt, filter_tags_via_llm


# -------------------------
# worker / queue
# -------------------------
def process_queue_item(request_id: str) -> None:
    request = task_status[request_id]["request"]
    url = request["url"]
    model = request["model"]
    asyncio.run(_process_and_save(url=url, model=model, request_id=request_id))


# -------------------------
# html fetch + heuristics
# -------------------------
def fetch_and_clean_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; summary-bot/1.0; +https://example.com)"
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    doc = Document(response.text)
    cleaned_html = doc.summary()

    soup = BeautifulSoup(cleaned_html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)  # <-- keep spaces

    if not is_article(text):
        # In background worker it’s fine to raise HTTPException too (you catch it),
        # but you could also raise ValueError here if you prefer.
        if not is_article_llm(text):
            raise HTTPException(status_code=400, detail="The provided URL does not contain a valid article.")

    return text


def is_article(text: str) -> bool:
    text = text.strip()
    if len(text) < 500:
        return False

    sentences = re.split(r"[.!?]", text)
    long_sentences = [s for s in sentences if len(s.strip().split()) > 6]
    if len(long_sentences) < 5:
        return False

    lower = text.lower()
    if any(term in lower for term in [
        "404", "page not found", "not found", "cookies", "consent",
        "login required", "sign in to continue"
    ]):
        return False

    return True


def build_is_article_prompt(text: str) -> str:
    return f"""You are a web content classifier.

Determine whether the following page is a real article or not. An article should be at least one paragraph long, written in natural language, and contain meaningful content.

Only respond with a single word: "yes" or "no".

Here is the content:

{text[:2000]}"""


def is_article_llm(text: str) -> bool:
    prompt = build_is_article_prompt(text)
    try:
        response = call_ollama(prompt).strip().lower()
        return response.startswith("y")
    except Exception as e:
        log.error(f"[is_article_llm] Error during LLM check: {e}")
        return False


# -------------------------
# parsing helpers
# -------------------------
_JSON_BLOCK_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def _extract_json_block(text: str) -> str:
    s = (text or "").strip()

    # remove ```json fences if present
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
        s = s.strip()

    m = _JSON_BLOCK_RE.search(s)
    return (m.group(1) if m else s).strip()


def try_parse_result(raw: str) -> dict:
    extracted = _extract_json_block(raw)
    try:
        parsed = json.loads(extracted)
        if isinstance(parsed, dict) and "summary" in parsed and "tags" in parsed:
            return parsed
    except Exception:
        pass
    return {"raw_response": raw, "error": "Failed to parse"}


# -------------------------
# summary aggregation
# -------------------------
def summarize_chunk_summaries(summaries: list[str]) -> str:
    if not summaries:
        return "No summaries available."
    if len(summaries) == 1:
        return summaries[0]

    unique_summaries = list(dict.fromkeys(summaries))
    joined = " ".join(unique_summaries)

    prompt = f"""Summarize the following partial summaries into one single coherent summary (in one English sentence):\n\n{joined}"""
    raw = call_ollama(prompt)

    # Sometimes the model may output plain text here; just use it.
    text = raw.strip().strip('"')
    if 0 < len(text) < 500:
        return text

    return joined[:500].rsplit(".", 1)[0] + "..."


# -------------------------
# db write
# -------------------------
async def _process_and_save(url: str, model: str | None, request_id: str) -> None:
    # adjust this import name to match your database.py
    from app.db.database import SessionLocal  # if you used my updated database.py
    # if you still have async_session = sessionmaker(...), then use that instead.

    start_time = time()
    log.info(f"⚙️ Start processing: request_id={request_id}, url={url}")

    async with SessionLocal() as session:
        try:
            text = fetch_and_clean_html(url)
            prompt = build_prompt(text)

            prompt_tokens = len(encoding.encode(prompt, disallowed_special=()))
            text_tokens = len(encoding.encode(text, disallowed_special=()))
            log.info(f"⚙️ Symbols: {len(text)}, text tokens: {text_tokens}, prompt tokens: {prompt_tokens}")

            total_tokens_used = 0

            if prompt_tokens > MAX_TOKENS:
                chunks = chunk_text(text, max_tokens=CHUNK_MAX_TOKENS, overlap=CHUNK_OVERLAP)
                summaries: list[str] = []
                all_tags_list: list[list[str]] = []

                for idx, chunk in enumerate(chunks):
                    chunk_prompt = build_prompt(chunk)
                    chunk_prompt_tokens = len(encoding.encode(chunk_prompt, disallowed_special=()))
                    total_tokens_used += chunk_prompt_tokens

                    log.info(
                        f"🧩 Chunk #{idx + 1}/{len(chunks)}: chars={len(chunk)}, prompt_tokens={chunk_prompt_tokens}")

                    chunk_start_time = time()
                    chunk_result = call_ollama(prompt=chunk_prompt, model=model)
                    log.info(f"📨 LLM response for chunk #{idx + 1} (took {round(time() - chunk_start_time, 2)}s)")

                    parsed = try_parse_result(chunk_result)
                    if "summary" in parsed:
                        summaries.append(parsed["summary"])
                    if "tags" in parsed:
                        all_tags_list.append(parsed.get("tags", []))

                final_tags = filter_tags_via_llm(all_tags_list)
                final_summary = summarize_chunk_summaries(summaries)

                final_result = {
                    "url": url,
                    "summary": final_summary,
                    "tags": final_tags,
                    "chunks": len(chunks),
                }
            else:
                total_tokens_used = prompt_tokens
                result = call_ollama(prompt=prompt, model=model)
                parsed = try_parse_result(result)
                final_result = {"url": url, **parsed}

            # update runtime status
            task_status[request_id]["status"] = "success"
            task_status[request_id]["result"] = final_result

            # upsert-ish DB update
            row = await session.execute(select(Summary).where(Summary.url == url))
            entry = row.scalar_one_or_none()
            if entry is None:
                entry = Summary(url=url, status="success", model=model)
                session.add(entry)

            entry.status = "success"
            entry.result = json.dumps(final_result, ensure_ascii=False)
            entry.error = None
            entry.duration_sec = round(time() - start_time, 2)
            entry.total_tokens = total_tokens_used

            await session.commit()
            log.info(f"✅ Success: request_id={request_id}, url={url}, duration={entry.duration_sec} sec")

        except Exception as e:
            await session.rollback()

            task_status[request_id]["status"] = "failure"
            task_status[request_id]["error"] = str(e)

            row = await session.execute(select(Summary).where(Summary.url == url))
            entry = row.scalar_one_or_none()
            if entry is None:
                entry = Summary(url=url, status="failure", model=model)
                session.add(entry)

            entry.status = "failure"
            entry.error = str(e)

            await session.commit()
            log.error(f"❌ Error processing request_id={request_id}, url={url}: {e}")

        finally:
            with queue_lock:
                if request_id in task_queue:
                    task_queue.remove(request_id)
            log.info(f"🧹 Finished processing: request_id={request_id}")
