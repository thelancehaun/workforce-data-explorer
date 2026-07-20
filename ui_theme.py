"""
Shared visual identity for all charts.

Categorical palettes are validated (CVD-safe adjacent pairs, normal-vision
separation, surface contrast) per mode; the light palette must match
chartCategoricalColors in .streamlit/config.toml. Charts use transparent
backgrounds so they sit on whatever surface Streamlit's theme provides.
"""

from typing import Optional

import plotly.express as px
import streamlit as st

# Slot order is the CVD-safety mechanism — never reorder or cycle.
PALETTE_LIGHT = ["#2a78d6", "#008300", "#e87ba4", "#eda100", "#1baf7a", "#eb6834", "#4a3aa7", "#e34948"]
PALETTE_DARK = ["#3987e5", "#008300", "#d55181", "#c98500", "#199e70", "#d95926", "#9085e9", "#e66767"]

# Single-hue blue ramp for magnitude (sequential) encoding
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

_CHROME = {
    "light": {"grid": "#e1e0d9", "axis": "#c3c2b7", "muted": "#898781", "ink": "#0b0b0b"},
    "dark": {"grid": "#2c2c2a", "axis": "#383835", "muted": "#898781", "ink": "#fafafa"},
}

_FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def palette() -> list[str]:
    return PALETTE_DARK if _is_dark() else PALETTE_LIGHT


def style_fig(fig, height: Optional[int] = None, hovermode: str = "x unified"):
    """Apply the shared look to any plotly figure. Theme-adaptive."""
    dark = _is_dark()
    c = _CHROME["dark" if dark else "light"]
    fig.update_layout(
        template="plotly_dark" if dark else "plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=palette(),
        hovermode=hovermode,
        font=dict(family=_FONT, color=c["ink"], size=13),
        margin=dict(t=48, b=16, l=8, r=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title_text=""),
    )
    fig.update_xaxes(
        showgrid=False, linecolor=c["axis"], tickcolor=c["axis"],
        tickfont_color=c["muted"], title_font_color=c["muted"],
    )
    fig.update_yaxes(
        showgrid=True, gridcolor=c["grid"], gridwidth=1, zeroline=False,
        showline=False, tickfont_color=c["muted"], title_font_color=c["muted"],
    )
    # Only style the title when one exists — a title_font on a titleless
    # figure makes plotly render the literal string "undefined"
    if fig.layout.title and fig.layout.title.text:
        fig.update_layout(title_font=dict(size=15, color=c["ink"]))
    if height:
        fig.update_layout(height=height)
    return fig


def line(df, x, y, title: Optional[str] = None, height: Optional[int] = None, **px_kwargs):
    fig = px.line(df, x=x, y=y, title=title, color_discrete_sequence=palette(), **px_kwargs)
    fig.update_traces(line_width=2)
    return style_fig(fig, height=height)


def bar(df, x, y, title: Optional[str] = None, height: Optional[int] = None, horizontal: bool = False, **px_kwargs):
    fig = px.bar(
        df, x=x, y=y, title=title,
        orientation="h" if horizontal else "v",
        color_discrete_sequence=palette(), **px_kwargs,
    )
    return style_fig(fig, height=height, hovermode="closest" if horizontal else "x unified")
