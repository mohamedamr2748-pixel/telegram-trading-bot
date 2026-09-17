"""Telegram Trading Intelligence Bot application package."""

# Keep the existing chart implementation intact for advanced charts while
# transparently routing normal /price charts through the native OHLC candlestick
# renderer. This avoids a broad rewrite of the mature chart module.
from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path


def _install_chart_wrapper() -> None:
    if "app.charts" in sys.modules:
        return

    package = sys.modules[__name__]
    legacy_name = "app._legacy_charts"
    legacy = sys.modules.get(legacy_name)
    if legacy is None:
        charts_path = Path(__file__).with_name("charts.py")
        spec = importlib.util.spec_from_file_location(legacy_name, charts_path)
        if spec is None or spec.loader is None:
            raise ImportError("Could not load the legacy chart module")
        legacy = importlib.util.module_from_spec(spec)
        sys.modules[legacy_name] = legacy
        setattr(package, "_legacy_charts", legacy)
        spec.loader.exec_module(legacy)

    patch = importlib.import_module("app.candlestick_chart")
    wrapper = types.ModuleType("app.charts", "Chart compatibility wrapper")
    wrapper.__package__ = "app"
    wrapper.__file__ = str(Path(__file__).with_name("charts.py"))
    wrapper.__spec__ = None
    for name, value in vars(legacy).items():
        if name not in {"__name__", "__loader__", "__package__", "__spec__"}:
            setattr(wrapper, name, value)
    wrapper.render_google_finance_chart = patch.render_google_finance_chart
    wrapper.render_chart = patch.render_chart
    sys.modules["app.charts"] = wrapper
    setattr(package, "charts", wrapper)


_install_chart_wrapper()
