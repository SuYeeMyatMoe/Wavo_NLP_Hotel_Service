"""Static metric cards that do not load Streamlit's lazy Metric.js chunk."""

from html import escape
import streamlit as st


def metric_markup(label, value, *, help=None):
    label = escape(str(label))
    value = escape(str(value))
    explanation = (
        '<details class="wavo-metric-help">'
        f'<summary aria-label="About {label}"><span aria-hidden="true">?</span></summary>'
        f'<span class="wavo-metric-tooltip">{escape(str(help))}</span></details>'
        if help else ""
    )
    return (
        f'<dl class="wavo-metric" aria-label="{label}">'
        f'<dt><span class="wavo-metric-label">{label}</span>{explanation}</dt>'
        f'<dd>{value}</dd></dl>'
    )


def metric(label, value, *, help=None):
    st.html(metric_markup(label, value, help=help), width="stretch")
