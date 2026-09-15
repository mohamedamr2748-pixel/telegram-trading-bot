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
