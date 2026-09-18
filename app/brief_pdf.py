from __future__ import annotations

import textwrap
from datetime import datetime
from io import BytesIO
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch

BOT_USERNAME = "@TickaroBot"


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(str(text), width=width, break_long_words=False, replace_whitespace=False) or [""]


def _draw_box(ax, x: float, y: float, w: float, h: float, title: str, lines: list[str], accent: str = "#1f2937") -> None:
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.012,rounding_size=0.02",
        linewidth=0.8,
        edgecolor="#d1d5db",
        facecolor="#ffffff",
    )
    ax.add_patch(patch)
    ax.text(x + 0.02, y + h - 0.045, title, fontsize=10.5, fontweight="bold", color=accent, va="top")
    cursor = y + h - 0.085
    for line in lines:
        ax.text(x + 0.02, cursor, line, fontsize=8.4, color="#111827", va="top")
        cursor -= 0.037


def build_brief_pdf(report: dict[str, Any]) -> BytesIO:
    buffer = BytesIO()
    with PdfPages(buffer) as pdf:
        quotes = report.get("quotes", [])
        movers = report.get("movers", {})
        news = report.get("news", [])
        insights = report.get("cross_asset_insights", [])
        drivers = report.get("news_implications", [])
        risk_watch = report.get("risk_watch", [])
        watch_next = report.get("watch_next", [])

        page_count = 2 if news or drivers or risk_watch or watch_next else 1
        for page in range(page_count):
            fig = plt.figure(figsize=(8.5, 11), facecolor="#f8fafc")
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")

            ax.text(0.065, 0.945, "TICKARO", fontsize=10, fontweight="bold", color="#374151")
            ax.text(0.065, 0.905, "Daily Market Brief", fontsize=23, fontweight="bold", color="#111827")
            ax.text(
                0.065, 0.875,
                f"{_format_time(report.get('generated_at'))}  •  {report.get('market_regime', 'Mixed')}",
                fontsize=9.5, color="#6b7280",
            )
            ax.text(0.935, 0.945, BOT_USERNAME, fontsize=9, color="#4b5563", ha="right")

            if page == 0:
                summary_lines = _wrap(report.get("executive_summary", ""), 92)
                _draw_box(ax, 0.065, 0.735, 0.87, 0.115, "MARKET PULSE", summary_lines, "#111827")

                y = 0.68
                ax.text(0.065, y, "CROSS-ASSET SNAPSHOT", fontsize=11, fontweight="bold", color="#111827")
                y -= 0.035
                headers = ["Asset", "Price", "Move"]
                xs = [0.065, 0.52, 0.78]
                for x, h in zip(xs, headers):
                    ax.text(x, y, h, fontsize=8.5, fontweight="bold", color="#6b7280")
                y -= 0.032
                for quote in quotes[:5]:
                    ax.text(0.065, y, str(quote.get("label", quote.get("symbol", ""))), fontsize=9, color="#111827")
                    ax.text(0.52, y, str(quote.get("price_text", "n/a")), fontsize=9, color="#111827")
                    ax.text(0.78, y, str(quote.get("move_text", "n/a")), fontsize=9, color="#111827")
                    y -= 0.028

                insight_lines = []
                for item in insights[:4]:
                    insight_lines.extend(["• " + line for line in _wrap(item, 75)])
                _draw_box(ax, 0.065, 0.46, 0.87, 0.16, "CROSS-ASSET READ", insight_lines or ["No additional cross-asset insight available."])

                g = movers.get("gainers", [])[:3]
                l = movers.get("losers", [])[:3]
                mover_lines = ["GAINERS  " + "   ".join(f"{m.get('symbol','')} {float(m.get('percent_change',0)):+.2f}%" for m in g) or "GAINERS  n/a",
                               "LOSERS   " + "   ".join(f"{m.get('symbol','')} {float(m.get('percent_change',0)):+.2f}%" for m in l) or "LOSERS   n/a"]
                _draw_box(ax, 0.065, 0.29, 0.87, 0.12, "TOP MOVERS", mover_lines)

                pulse_line = [
                    f"Regime: {report.get('market_regime', 'Mixed')}",
                    f"Tracked assets: {len(quotes[:5])}",
                    f"Headline set: {len(news[:8])}",
                ]
                _draw_box(ax, 0.065, 0.165, 0.87, 0.085, "REPORT SNAPSHOT", pulse_line)

            else:
                ax.text(0.065, 0.82, "NEWS & MONITORING", fontsize=11, fontweight="bold", color="#111827")

                news_lines = []
                for idx, item in enumerate(news[:5], 1):
                    title = str(item.get("title", "Untitled"))
                    source = str(item.get("source", "Unknown"))
                    news_lines.extend([f"{idx}. {_wrap(title, 82)[0]}", f"   {source}"])
                    if len(_wrap(title, 82)) > 1:
                        news_lines.extend([f"   {line}" for line in _wrap(title, 82)[1:]])
                _draw_box(ax, 0.065, 0.58, 0.87, 0.20, "HEADLINES", news_lines or ["No recent headlines available."])

                driver_lines = []
                news_map = {str(item.get("id")): item for item in news}
                for item in drivers[:5]:
                    headline = news_map.get(str(item.get("news_id")))
                    label = headline.get("title", "Selected headline") if headline else "Selected headline"
                    for line in _wrap(f"• {label}: {item.get('point','')}", 82):
                        driver_lines.append(line)
                _draw_box(ax, 0.065, 0.37, 0.87, 0.16, "NEWS SIGNALS", driver_lines or ["No specific headline signal was identified."])

                risk_lines = ["• " + line for item in risk_watch[:4] for line in _wrap(item, 82)]
                _draw_box(ax, 0.065, 0.20, 0.42, 0.13, "RISK WATCH", risk_lines or ["None supplied."])

                next_lines = ["• " + line for item in watch_next[:4] for line in _wrap(item, 39)]
                _draw_box(ax, 0.515, 0.20, 0.42, 0.13, "WATCH NEXT", next_lines or ["None supplied."])

            ax.text(
                0.065, 0.08,
                f"{BOT_USERNAME}  •  Market information and AI-generated context for orientation only; not personalised investment advice.",
                fontsize=7.5, color="#6b7280",
            )
            fig.savefig(pdf, format="pdf", bbox_inches="tight")
            plt.close(fig)

    buffer.seek(0)
    return buffer


def _format_time(value: Any) -> str:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y • %H:%M UTC")
    except (TypeError, ValueError):
        return "Generated time unavailable"
