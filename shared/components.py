"""
Shared UI Components for Dashboard Pages
Reusable alert banners, metric cards, and charts
"""

import streamlit as st
import plotly.graph_objects as go
from typing import Dict, List, Optional

def render_connection_status(vllm_available: bool, ollama_available: bool):
    """
    Render connection status indicators for vLLM and Ollama
    """
    col1, col2 = st.columns(2)

    with col1:
        if vllm_available:
            st.markdown("""
            <div style="padding: 0.5rem; background: #ecfdf5; border-left: 3px solid #10b981; border-radius: 0.3rem;">
                <span style="color: #065f46;">🟢 vLLM Connected</span> (port 8080)
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="padding: 0.5rem; background: #fef2f2; border-left: 3px solid #ef4444; border-radius: 0.3rem;">
                <span style="color: #991b1b;">🔴 vLLM Disconnected</span>
            </div>
            """, unsafe_allow_html=True)
            st.error("⚠️ Run: `oc port-forward -n <namespace> pod/<vllm-pod> 8080:8080`")

    with col2:
        if ollama_available:
            st.markdown("""
            <div style="padding: 0.5rem; background: #ecfdf5; border-left: 3px solid #10b981; border-radius: 0.3rem;">
                <span style="color: #065f46;">🟢 Ollama AI Ready</span> (port 11434)
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="padding: 0.5rem; background: #fef2f2; border-left: 3px solid #ef4444; border-radius: 0.3rem;">
                <span style="color: #991b1b;">🔴 Ollama Not Running</span>
            </div>
            """, unsafe_allow_html=True)
            st.error("⚠️ AI insights unavailable. Start Ollama: `ollama serve`")


def render_alert_banner(severity: str, title: str, message: str, show_expand: bool = False, expanded_content: str = ""):
    """
    Render alert banner with severity-based styling (RHOAI UX best practices)

    Args:
        severity: "critical", "warning", or "info"
        title: Alert title
        message: Main message
        show_expand: Whether to show expandable details
        expanded_content: Content for expandable section
    """
    severity_styles = {
        "critical": {
            "bg": "#fef2f2",
            "color": "#991b1b",
            "border": "#dc2626"
        },
        "warning": {
            "bg": "#fffbeb",
            "color": "#92400e",
            "border": "#f59e0b"
        },
        "info": {
            "bg": "#eff6ff",
            "color": "#1e40af",
            "border": "#3b82f6"
        }
    }

    style = severity_styles.get(severity.lower(), severity_styles["info"])

    st.markdown(f"""
    <div style="
        background: {style['bg']};
        color: {style['color']};
        border-left: 4px solid {style['border']};
        padding: 1.2rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    ">
        <strong style="font-size: 1.1rem;">{title}</strong><br/>
        <div style="margin-top: 0.5rem;">{message}</div>
    </div>
    """, unsafe_allow_html=True)

    if show_expand and expanded_content:
        with st.expander("📖 See Details"):
            st.markdown(expanded_content)


def render_metric_card(label: str, value: str, delta: Optional[str] = None, help_text: str = "", color: str = "blue"):
    """
    Render metric card with context (delta and help text)

    Args:
        label: Metric label
        value: Current value
        delta: Change indicator (e.g., "+12% vs 1h ago")
        help_text: Explanation tooltip
        color: Border color ("blue", "green", "red", "orange")
    """
    color_map = {
        "blue": "#3b82f6",
        "green": "#10b981",
        "red": "#ef4444",
        "orange": "#f59e0b"
    }

    border_color = color_map.get(color, color_map["blue"])

    delta_html = f'<div style="color: #6b7280; font-size: 0.85rem; margin-top: 0.25rem;">{delta}</div>' if delta else ""

    st.markdown(f"""
    <div style="
        background: white;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 3px solid {border_color};
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    ">
        <div style="color: #6b7280; font-size: 0.85rem; margin-bottom: 0.25rem;">{label}</div>
        <div style="font-size: 1.8rem; font-weight: bold; color: #111827;">{value}</div>
        {delta_html}
        {f'<div style="color: #9ca3af; font-size: 0.75rem; margin-top: 0.5rem;">ℹ️ {help_text}</div>' if help_text else ""}
    </div>
    """, unsafe_allow_html=True)


def render_metric_chart(
    title: str,
    timestamps: List[str],
    values: List[float],
    threshold: Optional[float] = None,
    threshold_label: str = "Threshold",
    y_label: str = "",
    color: str = "#3b82f6"
):
    """
    Render time-series chart with optional threshold line

    Args:
        title: Chart title
        timestamps: List of timestamp strings
        values: List of metric values
        threshold: Optional threshold line value
        threshold_label: Label for threshold
        y_label: Y-axis label
        color: Line color
    """
    fig = go.Figure()

    # Main data line
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=values,
        mode='lines+markers',
        name=title,
        line=dict(color=color, width=2),
        marker=dict(size=6)
    ))

    # Threshold line if provided
    if threshold is not None:
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=[threshold] * len(timestamps),
            mode='lines',
            name=threshold_label,
            line=dict(color='red', width=2, dash='dash'),
            showlegend=True
        ))

    fig.update_layout(
        title=title,
        xaxis_title="Time",
        yaxis_title=y_label,
        height=300,
        margin=dict(l=50, r=20, t=40, b=40),
        hovermode='x unified',
        showlegend=True
    )

    st.plotly_chart(fig, use_container_width=True)


def render_commands_section(commands: List[Dict[str, str]], severity: str = "info"):
    """
    Render actionable commands section with copy buttons

    Args:
        commands: List of dicts with 'description', 'command', 'expected', 'risk'
        severity: Severity level for styling
    """
    if not commands:
        return

    st.markdown("### 🔧 Recommended Actions")

    for i, cmd in enumerate(commands):
        with st.expander(f"Action {i+1}: {cmd.get('description', 'Fix')}", expanded=(i==0)):
            st.code(cmd['command'], language='bash')

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Expected:** {cmd.get('expected', 'Improvement')}")
            with col2:
                st.markdown(f"**Risk:** {cmd.get('risk', 'Low')}")

            if cmd.get('verify'):
                st.info(f"✓ Verify: {cmd['verify']}")


def render_empty_state(message: str, icon: str = "📊"):
    """
    Render empty state message
    """
    st.markdown(f"""
    <div style="
        text-align: center;
        padding: 3rem;
        background: #f9fafb;
        border-radius: 0.5rem;
        border: 2px dashed #d1d5db;
    ">
        <div style="font-size: 3rem; margin-bottom: 1rem;">{icon}</div>
        <div style="color: #6b7280; font-size: 1.1rem;">{message}</div>
    </div>
    """, unsafe_allow_html=True)


def render_progress_bar(value: float, max_value: float, label: str = "", color: str = "blue"):
    """
    Render progress bar with percentage
    """
    percentage = (value / max_value * 100) if max_value > 0 else 0

    color_map = {
        "blue": "#3b82f6",
        "green": "#10b981",
        "red": "#ef4444",
        "orange": "#f59e0b"
    }

    bar_color = color_map.get(color, color_map["blue"])

    st.markdown(f"""
    <div style="margin-bottom: 1rem;">
        {f'<div style="color: #6b7280; font-size: 0.85rem; margin-bottom: 0.25rem;">{label}</div>' if label else ''}
        <div style="background: #e5e7eb; border-radius: 1rem; height: 24px; overflow: hidden;">
            <div style="
                background: {bar_color};
                width: {percentage}%;
                height: 100%;
                border-radius: 1rem;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 0.8rem;
                font-weight: bold;
            ">
                {percentage:.1f}%
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
