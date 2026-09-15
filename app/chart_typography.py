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
        # "Prev close\n<value>". Replace that with a clean single-line
        # annotation, keeping the label regular and the value bold.
        if isinstance(s, str) and s.startswith("Prev close\n"):
            value_text = s.split("\n", 1)[1]
            try:
                value_text = f"{float(value_text.replace(',', '')):,.2f}"
            except (TypeError, ValueError):
                pass

            base_kwargs = dict(kwargs)
            base_kwargs["va"] = "center"
            base_kwargs["transform"] = kwargs.get("transform", self.get_yaxis_transform())

            if "fontsize" in base_kwargs:
                try:
                    base_kwargs["fontsize"] = float(base_kwargs["fontsize"]) * scale
                except (TypeError, ValueError):
                    pass
            elif "size" in base_kwargs:
                try:
                    base_kwargs["size"] = float(base_kwargs["size"]) * scale
                except (TypeError, ValueError):
                    pass

            label_kwargs = dict(base_kwargs)
            label_kwargs["ha"] = "right"
            label_kwargs["color"] = kwargs.get("color", "#d5d8de")

            value_kwargs = dict(base_kwargs)
            value_kwargs["ha"] = "right"
            value_kwargs["fontweight"] = "bold"
            value_kwargs["color"] = kwargs.get("color", "#f8fafc")

            # Keep both pieces on the same horizontal line and inside the
            # plotting area so neither collides with the right-side axis ticks.
            original_axes_text(
                self,
                0.930,
                y,
                "Prev. close",
                *args,
                **label_kwargs,
            )
            original_axes_text(
                self,
                0.995,
                y,
                value_text,
                *args,
                **value_kwargs,
            )
            return self.texts[-1]

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
