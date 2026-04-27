"""
Theme Configuration - Dark/Light Mode Support
"""

import streamlit as st

def get_theme_css(dark_mode: bool = False):
    """
    Get theme-specific CSS

    Args:
        dark_mode: True for dark mode, False for light mode
    """

    if dark_mode:
        return """
        <style>
            /* Dark Mode Theme */
            .main {
                background-color: #0e1117;
                color: #fafafa;
            }

            .main-header {
                font-size: 2.5rem;
                font-weight: bold;
                color: #58a6ff;
                margin-bottom: 1rem;
            }

            /* Alert Banners - Dark Mode */
            .alert-banner {
                padding: 1.2rem;
                border-radius: 0.5rem;
                margin-bottom: 1rem;
                font-size: 1rem;
                line-height: 1.5;
                border-left: 4px solid;
            }
            .alert-critical {
                background: #2d1117;
                color: #ffa7c4;
                border-left-color: #f85149;
            }
            .alert-warning {
                background: #2d2408;
                color: #f0ce85;
                border-left-color: #d29922;
            }
            .alert-info {
                background: #0d1d2d;
                color: #79c0ff;
                border-left-color: #1f6feb;
            }

            /* Metric Cards - Dark Mode */
            .metric-card {
                background: #161b22;
                padding: 1.2rem;
                border-radius: 0.5rem;
                box-shadow: 0 1px 3px rgba(0,0,0,0.5);
                border-left: 3px solid #1f6feb;
                color: #fafafa;
            }

            /* Status Indicators */
            .status-indicator {
                display: inline-block;
                width: 10px;
                height: 10px;
                border-radius: 50%;
                margin-right: 8px;
            }
            .status-connected {
                background: #3fb950;
                box-shadow: 0 0 8px #3fb950;
            }
            .status-disconnected {
                background: #f85149;
                box-shadow: 0 0 8px #f85149;
            }

            /* Tables */
            .dataframe {
                background: #161b22;
                color: #fafafa;
            }

            /* Code blocks */
            code {
                background: #161b22;
                color: #79c0ff;
            }
        </style>
        """
    else:
        return """
        <style>
            /* Light Mode Theme */
            .main {
                background-color: #ffffff;
                color: #24292f;
            }

            .main-header {
                font-size: 2.5rem;
                font-weight: bold;
                color: #1f77b4;
                margin-bottom: 1rem;
            }

            /* Alert Banners - Light Mode */
            .alert-banner {
                padding: 1.2rem;
                border-radius: 0.5rem;
                margin-bottom: 1rem;
                font-size: 1rem;
                line-height: 1.5;
                border-left: 4px solid;
            }
            .alert-critical {
                background: #fef2f2;
                color: #991b1b;
                border-left-color: #dc2626;
            }
            .alert-warning {
                background: #fffbeb;
                color: #92400e;
                border-left-color: #f59e0b;
            }
            .alert-info {
                background: #eff6ff;
                color: #1e40af;
                border-left-color: #3b82f6;
            }

            /* Metric Cards - Light Mode */
            .metric-card {
                background: white;
                padding: 1.2rem;
                border-radius: 0.5rem;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                border-left: 3px solid #3b82f6;
            }

            /* Status Indicators */
            .status-indicator {
                display: inline-block;
                width: 10px;
                height: 10px;
                border-radius: 50%;
                margin-right: 8px;
            }
            .status-connected {
                background: #10b981;
                box-shadow: 0 0 8px #10b981;
            }
            .status-disconnected {
                background: #ef4444;
                box-shadow: 0 0 8px #ef4444;
            }

            /* Progressive Disclosure */
            .stExpander {
                border: 1px solid #e5e7eb;
                border-radius: 0.5rem;
            }
        </style>
        """


def render_theme_toggle():
    """
    Render theme toggle button in sidebar

    Returns:
        bool: True if dark mode enabled
    """
    if 'dark_mode' not in st.session_state:
        st.session_state.dark_mode = False

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🎨 Theme")

    theme_label = "🌙 Dark Mode" if not st.session_state.dark_mode else "☀️ Light Mode"

    if st.sidebar.button(theme_label, use_container_width=True):
        st.session_state.dark_mode = not st.session_state.dark_mode
        st.rerun()

    return st.session_state.dark_mode
