from __future__ import annotations

import json
import logging
import time

import httpx

from config import settings

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL_CHAIN = [
    settings.openrouter_model.strip() or "google/gemma-4-26b-a4b-it:free",
    settings.openrouter_fallback_model.strip() or "nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/free",
]
CACHE_TTL = 300
_cache: dict[str, tuple[float, list[int], str]] = {}

def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    decoder = json.JSONDecoder()
    start = cleaned.find("{")
    if start >= 0:
        cleaned = cleaned[start:]
    payload, _ = decoder.raw_decode(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("AI returned a non-object JSON payload")
    return payload

async def curate_news(symbol: str, items: list, limit: int = 5) -> tuple[list, str]:
    candidates = items[:12]
    if not candidates:
        return [], "no-candidates"

    fingerprint = json.dumps([
        {
            "title": item.title,
            "source": item.source,
            "url": item.url,
            "published_at": item.published_at.isoformat() if item.published_at else None,
        }
        for item in candidates
    ], sort_keys=True, ensure_ascii=False)
    key = f"{symbol.upper()}::{fingerprint}"
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and cached[0] > now:
        indexes, model = cached[1], cached[2]
        return [candidates[i] for i in indexes if 0 <= i < len(candidates)][:limit], model

    articles = [
        {
            "id": i,
            "title": item.title,
            "source": item.source,
            "published_at": item.published_at.isoformat() if item.published_at else None,
        }
        for i, item in enumerate(candidates)
    ]
    prompt = (
        f"Select the most important recent financial news articles for {symbol.upper()}.\n\n"
        f"Only choose from the supplied articles. Rank by direct relevance, materiality, recency, and source quality.\n"
        f"Return JSON only as {{\"selected_ids\":[0,1,2]}}. Select at most {limit}. Prefer fewer articles over weak or repetitive ones.\n\n"
        + json.dumps(articles, ensure_ascii=False, separators=(",", ":"))
    )

    errors = []
    for model in MODEL_CHAIN[:3]:
        try:
            key_value = settings.openrouter_api_key.strip()
            if not key_value:
                raise RuntimeError("OPENROUTER_API_KEY is not configured")
            headers = {
                "Authorization": f"Bearer {key_value}",
                "Content-Type": "application/json",
                "HTTP-Referer": settings.openrouter_referer or "https://tickaro.app",
                "X-Title": "Tickaro News Intelligence",
            }
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a financial news curator. Select only from supplied articles and never invent facts."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": 160,
                "reasoning_effort": "none",
                "response_format": {"type": "json_object"},
            }
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(OPENROUTER_URL, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
            choices = data.get("choices") or []
            content = (choices[0].get("message", {}) or {}).get("content") if choices else None
            if not isinstance(content, str) or not content.strip():
                raise ValueError("AI returned empty content")
            payload = _parse_json(content)
            raw_ids = payload.get("selected_ids", [])
            selected_ids = []
            if isinstance(raw_ids, list):
                for raw_id in raw_ids:
                    if isinstance(raw_id, int) and 0 <= raw_id < len(candidates) and raw_id not in selected_ids:
                        selected_ids.append(raw_id)
                    if len(selected_ids) >= limit:
                        break
            if not selected_ids:
                raise ValueError("AI selected no valid articles")
            _cache[key] = (now + CACHE_TTL, selected_ids, model)
            return [candidates[i] for i in selected_ids], model
        except Exception as exc:
            errors.append(f"{model}: {exc}")
            logger.warning("News AI curation failed: %s", errors[-1])
            if "429" in str(exc) or "Too Many Requests" in str(exc):
                break

    fallback = candidates[:limit]
    return fallback, "deterministic-fallback"