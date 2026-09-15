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
        # "Prev close\n<value>". Render it as one compact annotation just
        # above the dashed reference line, without overlapping the axis.
        if isinstance(s, str) and s.startswith("Prev close\n"):
            value_text = s.split("\n", 1)[1]
            try:
                value_text = f"{float(value_text.replace(',', '')):,.2f}"
            except (TypeError, ValueError):
                pass

            text_kwargs = dict(kwargs)
            text_kwargs["ha"] = "right"
            text_kwargs["va"] = "bottom"
            text_kwargs["transform"] = kwargs.get("transform", self.get_yaxis_transform())
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

            # Place the whole annotation above the reference line. Keep it
            # inside the axes, leaving the right-axis tick labels untouched.
            label_artist = original_axes_text(
                self,
                0.930,
                y + offset if False else y,
                "Prev. close",
                *args,
                **text_kwargs,
            )

            # The requested visual is "Prev. close 7,619.98". Draw the value
            # immediately to the right of the label, using a small display-space
            # offset so the two pieces remain together at any figure size.
            renderer = self.figure.canvas.get_renderer()
            bbox = label_artist.get_window_extent(renderer=renderer)
            try:
                inv = self.transAxes.inverted()
                value_x = float(inv.transform((bbox.x1 + 5.0, bbox.y0))[0])
            except Exception:
                value_x = 0.995

            value_kwargs = dict(text_kwargs)
            value_kwargs["fontweight"] = "bold"
            value_artist = original_axes_text(
                self,
                value_x,
                y,
                value_text,
                *args,
                **value_kwargs,
            )

            # Shift both artists upward together by a small amount in display
            # coordinates. This keeps the annotation clearly above the dashed
            # line instead of sitting directly on it.
            try:
                low, high = self.get_ylim()
                span = abs(float(high) - float(low))
                offset = max(span * 0.025, 0.01)
                label_artist.set_position((0.930, y + offset))
                value_artist.set_position((value_x, y + offset))
            except Exception:
                pass
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
