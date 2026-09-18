from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
BOT_USERNAME = "@TickaroBot"
PRIMARY_MODEL = "google/gemma-4-26b-a4b-it:free"
FALLBACK_MODEL = "openrouter/free"
CACHE_TTL_SECONDS = 5 * 60

_shared_cache: tuple[int, dict[str, Any]] | None = None


def _json_from_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"\x60{3}(?:json)?\s*(.*?)\s*\x60{3}", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()

    # Models can occasionally return a JSON object followed by extra commentary
    # or another JSON fragment. raw_decode lets us safely extract the first object.
    decoder = json.JSONDecoder()
    candidates = [cleaned]
    start = cleaned.find("{")
    if start > 0:
        candidates.append(cleaned[start:])

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            payload, _ = decoder.raw_decode(candidate.lstrip())
            if isinstance(payload, dict):
                return payload
            last_error = ValueError("OpenRouter returned a non-object JSON response")
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            last_error = exc

    raise ValueError(f"OpenRouter returned invalid JSON: {last_error}")


def _normalise_list(value: Any, max_items: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:max_items]:
        text = str(item).strip()
        if text:
            result.append(text)
    return result


def _normalise_drivers(value: Any, max_items: int = 5) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value[:max_items]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "news_id": str(item.get("news_id", "")).strip(),
                "point": str(item.get("point", "")).strip(),
                "impact": str(item.get("impact", "mixed")).strip().lower(),
            }
        )
    return [row for row in result if row["point"]]


def _normalise_report(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_regime": str(payload.get("market_regime", "Mixed")).strip() or "Mixed",
        "executive_summary": str(payload.get("executive_summary", "")).strip(),
        "cross_asset_insights": _normalise_list(payload.get("cross_asset_insights"), 4),
        "news_implications": _normalise_drivers(payload.get("news_implications"), 5),
        "risk_watch": _normalise_list(payload.get("risk_watch"), 4),
        "watch_next": _normalise_list(payload.get("watch_next"), 4),
        "data_quality": str(payload.get("data_quality", "Based only on the supplied market data and headlines.")).strip(),
    }


def _prompt(snapshot: dict[str, Any]) -> str:
    return f"""
You are the market-intelligence editor for {BOT_USERNAME}. Create a concise but information-dense Daily Market Brief for Telegram.

Hard rules:
- Use ONLY the facts in the supplied snapshot. Do not invent economic releases, earnings, central-bank decisions, causes, prices, statistics, or events.
- Headlines are evidence, not proof of causation. Use cautious wording such as "may be related to" or "the headline suggests".
- Do not give personalised investment advice, trade instructions, price targets, buy/sell calls, or predictions of market direction.
- Distinguish observed facts from interpretation.
- Prefer specific cross-asset relationships over generic phrases.
- If the data is incomplete or stale, explicitly say so.
- Return VALID JSON ONLY. No markdown, no code fences, no commentary.

Required JSON schema (do not add extra top-level keys):
{{
  "market_regime": "Risk-on | Risk-off | Mixed | Neutral",
  "executive_summary": "2-3 sentences, max 450 characters",
  "cross_asset_insights": ["3-4 concise insights, each max 180 characters"],
  "news_implications": [
    {{"news_id":"N1","point":"Why this supplied headline matters in context, max 220 characters","impact":"positive|negative|mixed|neutral"}}
  ],
  "risk_watch": ["3-4 concrete things to monitor, max 150 characters each"],
  "watch_next": ["3-4 near-term market data/events to monitor ONLY if supported by the supplied snapshot, max 150 characters each"],
  "data_quality": "One sentence describing freshness/coverage limitations"
}}

SNAPSHOT:
{json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))}
""".strip()


async def _request(model: str, prompt: str) -> dict[str, Any]:
    key = settings.openrouter_api_key.strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": settings.openrouter_referer or "https://tickaro.app",
        "X-Title": "Tickaro Trading Intelligence",
    }
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a careful financial-market information editor. Never fabricate facts.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.15,
        "max_tokens": 1800,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(OPENROUTER_URL, headers=headers, json=body)
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise ValueError("OpenRouter returned no choices")
    message = choices[0].get("message", {}) or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        finish_reason = choices[0].get("finish_reason", "unknown")
        refusal = message.get("refusal")
        raise ValueError(
            f"OpenRouter returned empty content (finish_reason={finish_reason}, refusal={refusal!r})"
        )
    return _normalise_report(_json_from_text(content))


def _fallback_report(snapshot: dict[str, Any], reason: str) -> dict[str, Any]:
    quotes = snapshot.get("quotes", [])
    valid = [q for q in quotes if isinstance(q, dict) and q.get("change_percent") is not None]
    positives = sum(float(q["change_percent"]) > 0 for q in valid)
    negatives = sum(float(q["change_percent"]) < 0 for q in valid)
    regime = "Risk-on" if positives >= 3 else "Risk-off" if negatives >= 3 else "Mixed"

    ranked = sorted(
        valid,
        key=lambda q: abs(float(q["change_percent"])),
        reverse=True,
    )
    if ranked:
        lead = ranked[0]
        summary = (
            f"{lead['label']} is showing the largest move in the supplied cross-asset snapshot "
            f"at {float(lead['change_percent']):+.2f}%. The overall tone is {regime.lower()} across the tracked assets."
        )
    else:
        summary = "The supplied market snapshot does not contain enough valid percentage changes for a detailed cross-asset read."

    insights = []
    for quote in ranked[:4]:
        insights.append(
            f"{quote['label']} is {float(quote['change_percent']):+.2f}% on the supplied snapshot."
        )

    news_implications = []
    for item in snapshot.get("news", [])[:4]:
        if isinstance(item, dict):
            news_implications.append(
                {
                    "news_id": str(item.get("id", "")),
                    "point": "Headline supplied for context; the available data does not establish causation.",
                    "impact": "neutral",
                }
            )

    return {
        "market_regime": regime,
        "executive_summary": summary,
        "cross_asset_insights": insights,
        "news_implications": news_implications,
        "risk_watch": [
            "Watch whether the largest cross-asset moves persist or mean-revert.",
            "Check fresh market data before acting on a stale snapshot.",
            "Treat headlines as context rather than confirmed causal explanations.",
        ],
        "watch_next": [
            "Updated index and asset prices",
            "Fresh market-moving headlines",
            "Changes in the top-mover list",
        ],
        "data_quality": f"AI analysis unavailable for this run ({reason}); deterministic summary shown instead.",
    }


async def generate_market_brief(snapshot: dict[str, Any]) -> dict[str, Any]:
    global _shared_cache
    bucket = int(time.time() // CACHE_TTL_SECONDS)
    if _shared_cache and _shared_cache[0] == bucket:
        return _shared_cache[1]

    prompt = _prompt(snapshot)
    selected_model = settings.openrouter_model.strip() or PRIMARY_MODEL
    try:
        report = await _request(selected_model, prompt)
    except Exception as primary_exc:
        logger.warning("Primary OpenRouter brief model failed: %s", primary_exc)
        selected_model = settings.openrouter_fallback_model.strip() or FALLBACK_MODEL
        try:
            report = await _request(selected_model, prompt)
        except Exception as fallback_exc:
            logger.exception("OpenRouter fallback failed: %s", fallback_exc)
            report = _fallback_report(snapshot, str(fallback_exc)[:160])

    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["model"] = selected_model
    report["bot_username"] = BOT_USERNAME
    # Cache the complete report with the exact market/news snapshot used to generate it.
    # This prevents AI commentary from describing a different snapshot than the one shown to users.
    report.update(snapshot)
    _shared_cache = (bucket, report)
    return report
