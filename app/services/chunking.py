from __future__ import annotations

from functools import lru_cache
from typing import List

import tiktoken


@lru_cache(maxsize=8)
def _get_encoding(name: str = "cl100k_base"):
    return tiktoken.get_encoding(name)


def chunk_text(
    text: str,
    max_tokens: int,
    overlap: int = 0,
    *,
    encoding_name: str = "cl100k_base",
) -> List[str]:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= max_tokens:
        raise ValueError("overlap must be < max_tokens (otherwise loop won't progress)")

    enc = _get_encoding(encoding_name)
    tokens = enc.encode(text, disallowed_special=())

    if not tokens:
        return []

    step = max_tokens - overlap
    chunks: List[str] = []

    for start in range(0, len(tokens), step):
        end = min(start + max_tokens, len(tokens))
        chunks.append(enc.decode(tokens[start:end]))

        if end >= len(tokens):
            break

    return chunks
