from __future__ import annotations

import html
import math
from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BOT_USERNAME = "@TickaroBot"

INK = colors.HexColor("#0B1220")
INK_2 = colors.HexColor("#1E293B")
SLATE = colors.HexColor("#64748B")
MUTED = colors.HexColor("#94A3B8")
BORDER = colors.HexColor("#DCE3EA")
PAPER = colors.HexColor("#F7F9FB")
PANEL = colors.white
TEAL = colors.HexColor("#0F766E")
TEAL_BG = colors.HexColor("#ECFDF5")
GREEN = colors.HexColor("#047857")
GREEN_BG = colors.HexColor("#ECFDF5")
RED = colors.HexColor("#B91C1C")
RED_BG = colors.HexColor("#FEF2F2")
AMBER = colors.HexColor("#B45309")
AMBER_BG = colors.HexColor("#FFFBEB")


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _num(value: Any, decimals: int = 2) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "n/a"


def _pct(value: Any) -> str:
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _time(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d %b %Y | %H:%M UTC")
    except (TypeError, ValueError):
        return "Time unavailable"


def _f(value: Any) -> float | None:
    try:
        number = float(value)
        return None if math.isnan(number) else number
    except (TypeError, ValueError):
        return None


def _move_colour(value: Any) -> colors.Color:
    number = _f(value)
    if number is None or number == 0:
        return SLATE
    return GREEN if number > 0 else RED


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    return {
        "hero": ParagraphStyle(
            "hero", parent=base, fontName="Helvetica-Bold", fontSize=23, leading=25,
            textColor=INK, spaceAfter=0,
        ),
        "meta": ParagraphStyle(
            "meta", parent=base, fontName="Helvetica", fontSize=8.5, leading=10.5,
            textColor=SLATE, spaceAfter=0,
        ),
        "section": ParagraphStyle(
            "section", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=12.5,
            textColor=INK, spaceAfter=4,
        ),
        "section_teal": ParagraphStyle(
            "section_teal", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=12.5,
            textColor=TEAL, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base, fontName="Helvetica", fontSize=9.0, leading=12.2,
            textColor=INK_2, spaceAfter=0,
        ),
        "small": ParagraphStyle(
            "small", parent=base, fontName="Helvetica", fontSize=8.0, leading=10.6,
            textColor=INK_2, spaceAfter=0,
        ),
        "muted": ParagraphStyle(
            "muted", parent=base, fontName="Helvetica", fontSize=7.4, leading=9.0,
            textColor=SLATE, spaceAfter=0,
        ),
        "table_head": ParagraphStyle(
            "table_head", parent=base, fontName="Helvetica-Bold", fontSize=7.4, leading=8.6,
            textColor=SLATE, spaceAfter=0,
        ),
        "table": ParagraphStyle(
            "table", parent=base, fontName="Helvetica", fontSize=8.2, leading=10.2,
            textColor=INK_2, spaceAfter=0,
        ),
        "table_bold": ParagraphStyle(
            "table_bold", parent=base, fontName="Helvetica-Bold", fontSize=8.2, leading=10.2,
            textColor=INK, spaceAfter=0,
        ),
        "metric_label": ParagraphStyle(
            "metric_label", parent=base, fontName="Helvetica-Bold", fontSize=6.8, leading=8,
            textColor=SLATE, spaceAfter=0,
        ),
        "metric_value": ParagraphStyle(
            "metric_value", parent=base, fontName="Helvetica-Bold", fontSize=12.5, leading=14,
            textColor=INK, spaceAfter=0,
        ),
        "metric_sub": ParagraphStyle(
            "metric_sub", parent=base, fontName="Helvetica", fontSize=6.8, leading=8,
            textColor=MUTED, spaceAfter=0,
        ),
        "news_title": ParagraphStyle(
            "news_title", parent=base, fontName="Helvetica-Bold", fontSize=8.4, leading=11.0,
            textColor=INK, spaceAfter=1.5,
        ),
        "news_meta": ParagraphStyle(
            "news_meta", parent=base, fontName="Helvetica", fontSize=7.1, leading=8.8,
            textColor=SLATE, spaceAfter=2,
        ),
        "signal": ParagraphStyle(
            "signal", parent=base, fontName="Helvetica", fontSize=7.7, leading=10.2,
            textColor=INK_2, spaceAfter=0,
        ),
        "pill": ParagraphStyle(
            "pill", parent=base, fontName="Helvetica-Bold", fontSize=6.8, leading=8,
            textColor=TEAL, alignment=TA_RIGHT, spaceAfter=0,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base, fontName="Helvetica", fontSize=6.9, leading=8.2,
            textColor=MUTED, spaceAfter=0,
        ),
    }


def _section(title: str, styles: dict[str, ParagraphStyle], teal: bool = False):
    return Paragraph(_esc(title).upper(), styles["section_teal" if teal else "section"])


def _card(title: str, value: str, sub: str, styles: dict[str, ParagraphStyle], bg=PANEL):
    t = Table(
        [[Paragraph(_esc(title).upper(), styles["metric_label"])],
         [Paragraph(_esc(value), styles["metric_value"])],
         [Paragraph(_esc(sub), styles["metric_sub"])]],
        colWidths=[40 * mm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("BOX", (0, 0), (-1, -1), 0.65, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _hero(report: dict, styles: dict[str, ParagraphStyle]):
    regime = str(report.get("market_regime", "Mixed"))
    regime_colour = GREEN if regime.lower() == "risk-on" else RED if regime.lower() == "risk-off" else AMBER
    meta = (
        f"{_esc(_time(report.get('generated_at')))}"
        f"  |  <font color='#{regime_colour.hexval()[2:]}'><b>{_esc(regime.upper())}</b></font>"
    )
    table = Table(
        [
            [Paragraph("Daily Market Brief", styles["hero"]), Paragraph(_esc(BOT_USERNAME), styles["pill"])],
            [Paragraph(meta, styles["meta"]), ""],
            [Paragraph("MARKET PULSE", styles["metric_label"]), ""],
            [Paragraph(_esc(report.get("executive_summary", "No market pulse available.")), styles["body"]), ""],
        ],
        colWidths=[126 * mm, 25 * mm],
    )
    table.setStyle(TableStyle([
        ("SPAN", (0, 1), (1, 1)),
        ("SPAN", (0, 2), (1, 2)),
        ("SPAN", (0, 3), (1, 3)),
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.85, BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 3.2, regime_colour),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _market_table(quotes: list[dict], styles: dict[str, ParagraphStyle]):
    rows = [[
        Paragraph("ASSET", styles["table_head"]),
        Paragraph("PRICE", styles["table_head"]),
        Paragraph("MOVE", styles["table_head"]),
        Paragraph("SESSION", styles["table_head"]),
    ]]
    for q in quotes[:5]:
        move = q.get("change_percent")
        move_style = ParagraphStyle(
            f"mv_{q.get('symbol', len(rows))}",
            parent=styles["table_bold"],
            textColor=_move_colour(move),
        )
        session = str(q.get("market_status", "unknown")).replace("_", " ").title()
        if q.get("stale"):
            session += " | stale"
        rows.append([
            Paragraph(_esc(q.get("label", q.get("symbol", ""))), styles["table_bold"]),
            Paragraph(_esc(q.get("price_text", "n/a")), styles["table"]),
            Paragraph(_esc(_pct(move)), move_style),
            Paragraph(_esc(session), styles["table"]),
        ])

    t = Table(rows, colWidths=[47 * mm, 38 * mm, 29 * mm, 54 * mm], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, BORDER),
        ("GRID", (0, 1), (-1, -1), 0.3, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PANEL, colors.HexColor("#FCFDFE")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _movers(movers: dict, styles: dict[str, ParagraphStyle]):
    def make(title: str, items: list[dict], positive: bool):
        accent = GREEN if positive else RED
        bg = GREEN_BG if positive else RED_BG
        rows = [[Paragraph(title.upper(), ParagraphStyle(
            f"mh_{title}", parent=styles["table_head"], textColor=accent
        ))]]
        for i in range(3):
            item = items[i] if i < len(items) else {}
            pct_style = ParagraphStyle(
                f"mp_{title}_{i}", parent=styles["table_bold"], textColor=accent
            )
            rows.append([Table(
                [[
                    Paragraph(f"{i + 1:02d}", styles["muted"]),
                    Paragraph(_esc(item.get("symbol", "-")), styles["table_bold"]),
                    Paragraph(_esc(_pct(item.get("percent_change"))), pct_style),
                ]],
                colWidths=[12 * mm, 35 * mm, 22 * mm],
            )])
        t = Table(rows, colWidths=[69 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), bg),
            ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
            ("LINEBELOW", (0, 0), (-1, 0), 0.55, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return t

    grid = Table([[
        make("Gainers", movers.get("gainers", [])[:3], True),
        make("Losers", movers.get("losers", [])[:3], False),
    ]], colWidths=[75 * mm, 75 * mm])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return grid


def _insight_card(number: int, text: str, styles: dict[str, ParagraphStyle]):
    marker = Paragraph(f"<font color='#0F766E'><b>{number:02d}</b></font>", styles["table_bold"])
    body = Paragraph(_esc(text), styles["small"])
    t = Table([[marker, body]], colWidths=[13 * mm, 138 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.65, BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 2.3, TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _news_card(index: int, item: dict, driver: dict | None, styles: dict[str, ParagraphStyle]):
    title = _esc(item.get("title", "Untitled"))
    url = item.get("url")
    if url:
        href = html.escape(str(url), quote=True)
        title = f'<link href="{href}" color="#0F766E"><u>{title}</u></link>'

    impact = str((driver or {}).get("impact", "neutral")).lower()
    accent = GREEN if impact == "positive" else RED if impact == "negative" else AMBER
    bg = GREEN_BG if impact == "positive" else RED_BG if impact == "negative" else AMBER_BG

    signal_text = (driver or {}).get("point") or (
        "Headline retained as market context; available data does not establish causation."
    )

    inner = Table(
        [[
            Paragraph(f"{index:02d}. {title}", styles["news_title"]),
            Paragraph(_esc(impact.upper()), ParagraphStyle(
                f"impact_{index}", parent=styles["pill"], textColor=accent
            )),
        ], [
            Paragraph(
                f"{_esc(item.get('source', ''))}  |  {_esc(_time(item.get('published_at')))}",
                styles["news_meta"],
            ),
            "",
        ], [
            Paragraph(f"<b>Signal:</b> {_esc(signal_text)}", styles["signal"]),
            "",
        ]],
        colWidths=[126 * mm, 25 * mm],
    )
    inner.setStyle(TableStyle([
        ("SPAN", (0, 1), (1, 1)),
        ("SPAN", (0, 2), (1, 2)),
        ("BACKGROUND", (1, 0), (1, 0), bg),
        ("BOX", (0, 0), (-1, -1), 0.65, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
        ("LINEBELOW", (0, 1), (-1, 1), 0.35, BORDER),
    ]))
    return inner


def _watch_grid(risks: list[str], next_items: list[str], styles: dict[str, ParagraphStyle]):
    def panel(title: str, items: list[str], accent, bg):
        rows = [[Paragraph(_esc(title).upper(), ParagraphStyle(
            f"wg_{title}", parent=styles["table_head"], textColor=accent
        ))]]
        for item in items[:4]:
            rows.append([Paragraph(f"- {_esc(item)}", styles["small"])])
        if len(rows) == 1:
            rows.append([Paragraph("- None listed.", styles["small"])])
        t = Table(rows, colWidths=[73 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), bg),
            ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
            ("LINEBELOW", (0, 0), (-1, 0), 0.55, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    outer = Table([[
        panel("Risk Radar", risks, AMBER, AMBER_BG),
        panel("Watch Next", next_items, TEAL, TEAL_BG),
    ]], colWidths=[75 * mm, 75 * mm])
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def _header_footer(canvas, doc, report):
    canvas.saveState()
    width, height = A4

    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)

    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.65)
    canvas.line(18 * mm, height - 16 * mm, width - 18 * mm, height - 16 * mm)

    canvas.setFont("Helvetica-Bold", 8.2)
    canvas.setFillColor(INK)
    canvas.drawString(18 * mm, height - 11.5 * mm, "TICKARO")

    canvas.setFont("Helvetica", 7.6)
    canvas.setFillColor(SLATE)
    canvas.drawRightString(width - 18 * mm, height - 11.5 * mm, BOT_USERNAME)

    canvas.setStrokeColor(BORDER)
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)

    canvas.setFont("Helvetica", 6.9)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 8.7 * mm, "Tickaro | Daily Market Brief")
    canvas.drawRightString(width - 18 * mm, 8.7 * mm, f"Page {doc.page}")

    canvas.restoreState()


def _clean(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "quotes": report.get("quotes", []) if isinstance(report.get("quotes", []), list) else [],
        "movers": report.get("movers", {}) if isinstance(report.get("movers", {}), dict) else {},
        "news": report.get("news", []) if isinstance(report.get("news", []), list) else [],
        "cross_asset_insights": report.get("cross_asset_insights", []) if isinstance(report.get("cross_asset_insights", []), list) else [],
        "news_implications": report.get("news_implications", []) if isinstance(report.get("news_implications", []), list) else [],
        "risk_watch": report.get("risk_watch", []) if isinstance(report.get("risk_watch", []), list) else [],
        "watch_next": report.get("watch_next", []) if isinstance(report.get("watch_next", []), list) else [],
        "market_regime": report.get("market_regime", "Mixed"),
        "executive_summary": report.get("executive_summary", ""),
        "generated_at": report.get("generated_at"),
    }


def build_brief_pdf(report: dict[str, Any]) -> BytesIO:
    report = _clean(report)
    styles = _styles()
    quotes = report["quotes"]
    news = report["news"]
    moves = [q for q in quotes if q.get("change_percent") is not None]
    up = sum(1 for q in moves if _f(q.get("change_percent")) > 0)
    down = sum(1 for q in moves if _f(q.get("change_percent")) < 0)
    flat = max(len(moves) - up - down, 0)

    equities = [
        _f(q.get("change_percent"))
        for q in quotes
        if q.get("label") in {"S&P 500", "NASDAQ", "Dow Jones"} and q.get("change_percent") is not None
    ]
    equity_avg = sum(x for x in equities if x is not None) / len(equities) if equities else None
    largest = max(moves, key=lambda q: abs(_f(q.get("change_percent")) or 0), default=None)

    cards = Table([[
        _card("Breadth", f"{up} up / {down} down", f"{flat} flat", styles),
        _card("US equity avg", _pct(equity_avg), "S&P 500 / NASDAQ / Dow", styles),
        _card("Largest move", _pct(largest.get("change_percent") if largest else None), str(largest.get("label", "n/a") if largest else "n/a"), styles),
        _card("Headlines", str(len(news)), "market items tracked", styles),
    ]], colWidths=[40 * mm] * 4)
    cards.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    story: list[Any] = [
        Spacer(1, 7 * mm),
        _hero(report, styles),
        Spacer(1, 5 * mm),
        cards,
        Spacer(1, 7 * mm),
        _section("Cross-Asset Dashboard", styles),
        _market_table(quotes, styles),
        Spacer(1, 4.5 * mm),
        _section("Market Movers", styles, teal=True),
        _movers(report["movers"], styles),
        Spacer(1, 5 * mm),
        _section("Cross-Asset Read", styles),
    ]

    insights = report["cross_asset_insights"][:4]
    if insights:
        for index, insight in enumerate(insights, 1):
            story.append(_insight_card(index, str(insight), styles))
            story.append(Spacer(1, 2.2 * mm))
    else:
        story.append(_insight_card(1, "No additional cross-asset interpretation is available for this report.", styles))

    story.extend([
        Spacer(1, 5 * mm),
        _section("News Intelligence", styles),
        Spacer(1, 1 * mm),
    ])

    drivers = {
        str(x.get("news_id")): x
        for x in report["news_implications"]
        if isinstance(x, dict)
    }
    for index, item in enumerate(news[:5], 1):
        story.append(KeepTogether([
            _news_card(index, item, drivers.get(str(item.get("id"))), styles),
            Spacer(1, 2.2 * mm),
        ]))

    story.extend([
        _section("Monitoring", styles, teal=True),
        _watch_grid(report["risk_watch"], report["watch_next"], styles),
        Spacer(1, 5 * mm),
        HRFlowable(width="100%", thickness=0.55, color=BORDER, spaceBefore=0, spaceAfter=4 * mm),
        Paragraph(
            "Market information and AI-generated context for orientation only; not personalised investment advice.",
            styles["footer"],
        ),
    ])

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=16 * mm,
        title="Tickaro Daily Market Brief",
        author=BOT_USERNAME,
        subject="Market overview, cross-asset analysis, movers and news intelligence",
        creator="Tickaro",
    )
    doc.build(
        story,
        onFirstPage=lambda canvas, document: _header_footer(canvas, document, report),
        onLaterPages=lambda canvas, document: _header_footer(canvas, document, report),
    )
    buffer.seek(0)
    return buffer
