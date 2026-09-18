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
MODEL_CHAIN = [
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/free",
]
CACHE_TTL_SECONDS = 60 * 60

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
        "temperature": 0.1,
        "max_tokens": 900,
        "reasoning_effort": "none",
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=30) as client:
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


async def _request_chain(prompt: str) -> tuple[dict[str, Any], str]:
    errors: list[str] = []
    configured = settings.openrouter_model.strip()
    candidates = [configured] if configured else []
    candidates.extend(model for model in MODEL_CHAIN if model not in candidates)

    for model in candidates[:3]:
        try:
            return await _request(model, prompt), model
        except Exception as exc:
            message = str(exc)
            errors.append(f"{model}: {message}")
            logger.warning("OpenRouter model failed: %s", errors[-1])
            # Do not burn the remaining free-model quota when the account is rate limited.
            if "429" in message or "Too Many Requests" in message:
                break

    raise RuntimeError("All OpenRouter models failed: " + " | ".join(errors)[-700:])


def _fallback_report(snapshot: dict[str, Any], reason: str) -> dict[str, Any]:
    quotes = snapshot.get("quotes", [])
    valid = [q for q in quotes if isinstance(q, dict) and q.get("change_percent") is not None]
    positives = sum(float(q["change_percent"]) > 0 for q in valid)
    negatives = sum(float(q["change_percent"]) < 0 for q in valid)
    regime = "Risk-on" if positives >= 3 else "Risk-off" if negatives >= 3 else "Mixed"

    ranked = sorted(valid, key=lambda q: abs(float(q["change_percent"])), reverse=True)
    summary = (
        f"{len([q for q in valid if float(q['change_percent']) > 0])} of {len(valid)} tracked assets are higher, "
        f"while {len([q for q in valid if float(q['change_percent']) < 0])} are lower. "
        f"The largest absolute move is {ranked[0]['label']} at {float(ranked[0]['change_percent']):+.2f}%."
        if ranked else
        "The supplied snapshot does not contain enough valid percentage changes for a cross-asset read."
    )

    by_label = {str(q.get("label")): q for q in valid}
    insights: list[str] = []

    equity = [by_label.get("S&P 500"), by_label.get("NASDAQ"), by_label.get("Dow Jones")]
    equity = [q for q in equity if q]
    if equity:
        equity_avg = sum(float(q["change_percent"]) for q in equity) / len(equity)
        direction = "higher" if equity_avg > 0 else "lower" if equity_avg < 0 else "roughly flat"
        insights.append(f"US equity indices are {direction} on average across the supplied snapshot ({equity_avg:+.2f}% average move).")

    btc = by_label.get("Bitcoin")
    gold = by_label.get("Gold")
    if btc and equity:
        btc_move = float(btc["change_percent"])
        equity_avg = sum(float(q["change_percent"]) for q in equity) / len(equity)
        if btc_move > 0 and equity_avg < 0:
            insights.append("Bitcoin is moving higher while the main US equity indices are lower, indicating cross-asset divergence rather than a uniform move.")
        elif btc_move < 0 and equity_avg > 0:
            insights.append("Bitcoin is moving lower while the main US equity indices are higher, another sign of cross-asset divergence.")
        else:
            insights.append("Bitcoin and US equities are moving in the same broad direction in the supplied snapshot.")

    if gold:
        gold_move = float(gold["change_percent"])
        insights.append(f"Gold is {gold_move:+.2f}% in the supplied snapshot; compare its move with equities and Bitcoin before drawing broader conclusions.")

    for quote in ranked[:4]:
        label = quote["label"]
        move = float(quote["change_percent"])
        insights.append(f"{label} is {move:+.2f}% on the supplied snapshot.")

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
        "cross_asset_insights": insights[:4],
        "news_implications": news_implications,
        "risk_watch": [
            "Check whether the largest cross-asset moves persist in fresh data.",
            "Treat headline explanations as context unless supported by additional evidence.",
            "Re-check any stale quote before using it for decisions.",
        ],
        "watch_next": [
            "Updated US index prices",
            "Updated Bitcoin and Gold prices",
            "Fresh market-moving headlines",
            "Changes in the top-mover list",
        ],
        "data_quality": f"Automated fallback summary used because AI analysis was unavailable ({reason[:120]}).",
    }


async def generate_market_brief(snapshot: dict[str, Any]) -> dict[str, Any]:
    global _shared_cache
    bucket = int(time.time() // CACHE_TTL_SECONDS)
    if _shared_cache and _shared_cache[0] == bucket:
        return _shared_cache[1]

    prompt = _prompt(snapshot)
    try:
        report, selected_model = await _request_chain(prompt)
    except Exception as exc:
        logger.exception("OpenRouter model chain failed; using deterministic brief: %s", exc)
        report = _fallback_report(snapshot, str(exc)[:220])
        selected_model = "deterministic-fallback"

    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["model"] = selected_model
    report["bot_username"] = BOT_USERNAME
    # Cache the complete report with the exact market/news snapshot used to generate it.
    # This prevents AI commentary from describing a different snapshot than the one shown to users.
    report.update(snapshot)
    _shared_cache = (bucket, report)
    return report
