from __future__ import annotations

from functools import wraps


def install(scale: float = 1.28, x_axis_scale: float = 1.22) -> None:
    """Increase chart typography, with extra emphasis on time-axis labels."""
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    from app import charts

    if getattr(charts, "_chart_typography_installed", False):
        return

    original_render = charts.render_google_finance_chart
    original_axes_text = Axes.text
    original_axes_tick_params = Axes.tick_params
    original_figure_text = Figure.text

    @wraps(original_axes_text)
    def axes_text(self, x, y, s, *args, **kwargs):
        # The chart creates the previous-close annotation as:
        # "Prev close\n<value>". Render it as two adjacent text artists:
        # regular "Prev. close" followed by a bold value, both slightly
        # above the dashed reference line.
        if isinstance(s, str) and s.startswith("Prev close\n"):
            value_text = s.split("\n", 1)[1]
            try:
                value_text = f"{float(value_text.replace(',', '')):,.2f}"
            except (TypeError, ValueError):
                pass

            try:
                low, high = self.get_ylim()
                span = abs(float(high) - float(low))
                offset = max(span * 0.025, 0.01)
            except Exception:
                offset = 0.01

            text_kwargs = dict(kwargs)
            text_kwargs["transform"] = kwargs.get("transform", self.get_yaxis_transform())
            text_kwargs["va"] = "bottom"
            text_kwargs["color"] = kwargs.get("color", "#d5d8de")

            if "fontsize" in text_kwargs:
                try:
                    text_kwargs["fontsize"] = float(text_kwargs["fontsize"]) * scale
                except (TypeError, ValueError):
                    pass
            elif "size" in text_kwargs:
                try:
                    text_kwargs["size"] = float(text_kwargs["size"]) * scale
                except (TypeError, ValueError):
                    pass

            # Anchor the bold value near the right edge, then calculate the
            # label position from its rendered width. This guarantees the
            # visual order is exactly: "Prev. close  7,619.98".
            value_kwargs = dict(text_kwargs)
            value_kwargs["ha"] = "right"
            value_kwargs["fontweight"] = "bold"
            value_kwargs["color"] = "#f8fafc"
            value_artist = original_axes_text(
                self,
                0.995,
                y + offset,
                value_text,
                *args,
                **value_kwargs,
            )

            try:
                renderer = self.figure.canvas.get_renderer()
                bbox = value_artist.get_window_extent(renderer=renderer)
                inv = self.transAxes.inverted()
                gap_px = 6.0
                label_x = float(inv.transform((bbox.x0 - gap_px, bbox.y0))[0])
            except Exception:
                label_x = 0.925

            label_kwargs = dict(text_kwargs)
            label_kwargs["ha"] = "right"
            label_kwargs["fontweight"] = "normal"
            original_axes_text(
                self,
                label_x,
                y + offset,
                "Prev. close",
                *args,
                **label_kwargs,
            )
            return value_artist

        if "fontsize" in kwargs:
            try:
                kwargs["fontsize"] = float(kwargs["fontsize"]) * scale
            except (TypeError, ValueError):
                pass
        elif "size" in kwargs:
            try:
                kwargs["size"] = float(kwargs["size"]) * scale
            except (TypeError, ValueError):
                pass
        return original_axes_text(self, x, y, s, *args, **kwargs)

    @wraps(original_axes_tick_params)
    def axes_tick_params(self, *args, **kwargs):
        labelsize = kwargs.get("labelsize")
        if isinstance(labelsize, (int, float)):
            axis = kwargs.get("axis", "both")
            factor = scale * (x_axis_scale if axis == "x" else 1.0)
            kwargs["labelsize"] = labelsize * factor
        return original_axes_tick_params(self, *args, **kwargs)

    @wraps(original_figure_text)
    def figure_text(self, x, y, s, *args, **kwargs):
        if "fontsize" in kwargs:
            try:
                kwargs["fontsize"] = float(kwargs["fontsize"]) * scale
            except (TypeError, ValueError):
                pass
        elif "size" in kwargs:
            try:
                kwargs["size"] = float(kwargs["size"]) * scale
            except (TypeError, ValueError):
                pass
        return original_figure_text(self, x, y, s, *args, **kwargs)

    Axes.text = axes_text
    Axes.tick_params = axes_tick_params
    Figure.text = figure_text

    async def render_with_larger_type(*args, **kwargs):
        return await original_render(*args, **kwargs)

    charts.render_google_finance_chart = render_with_larger_type
    charts._chart_typography_installed = True
