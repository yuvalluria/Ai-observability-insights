#!/usr/bin/env python3
"""
AI Observability Dashboard - Main Entry Point
Single Streamlit app with multiple pages for vLLM monitoring
"""

import streamlit as st
import sys
import os

# Add shared directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'shared'))

# Page config - must be first Streamlit command
st.set_page_config(
    page_title="AI Observability Dashboard",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Theme support
from theme import get_theme_css, render_theme_toggle

# Initialize dark mode
if 'dark_mode' not in st.session_state:
    st.session_state.dark_mode = False

# Apply theme CSS
st.markdown(get_theme_css(st.session_state.dark_mode), unsafe_allow_html=True)

# Additional custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        margin-bottom: 1rem;
    }

    /* Alert Banners - Subtle backgrounds with bold borders */
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

    /* Metric Cards with Context */
    .metric-card {
        background: white;
        padding: 1.2rem;
        border-radius: 0.5rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        border-left: 3px solid #3b82f6;
    }

    /* Connection Status Indicator */
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
    .status-connecting {
        background: #f59e0b;
        box-shadow: 0 0 8px #f59e0b;
    }

    /* Progressive Disclosure */
    .stExpander {
        border: 1px solid #e5e7eb;
        border-radius: 0.5rem;
    }

    /* Better table styling */
    .dataframe {
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)

# Main page content
st.markdown('<div class="main-header">AI Observability Dashboard</div>', unsafe_allow_html=True)

st.markdown("""
Welcome to the AI Observability Dashboard for vLLM model serving on Red Hat OpenShift.

### 📊 Available Views:

**👉 [Model Serving Monitor](/Model_Serving)** - Real-time metrics and AI insights for individual vLLM deployments
- Live GPU utilization, KV cache usage, latency metrics
- AI-powered bottleneck detection and recommendations
- Interactive chat for metrics analysis

**👉 [Cluster Overview](/Cluster_View)** - Aggregate metrics across all vLLM services
- Multi-service monitoring and comparison
- Resource usage by namespace
- Cluster-wide performance trends

---

### 🚀 Quick Start:

1. **Port-forward to vLLM pod:**
   ```bash
   oc port-forward -n <namespace> pod/<vllm-pod-name> 8080:8080
   ```

2. **Start Ollama (required for AI insights):**
   ```bash
   ollama serve
   ollama pull granite3-dense:8b
   ```

3. **Navigate to a dashboard** using the sidebar

---

### 📚 Documentation:
- [README.md](https://github.com/yuvalluria/Ai-observability-insights/blob/main/README.md) - Setup guide
- [QUICKSTART.md](https://github.com/yuvalluria/Ai-observability-insights/blob/main/QUICKSTART.md) - 5-minute tutorial
""")

# Sidebar instructions
with st.sidebar:
    st.markdown("### 🔍 AI Observability Dashboard")
    st.markdown("---")

    # Connection status check
    import requests

    st.markdown("#### System Status")

    # Check vLLM connection
    try:
        response = requests.get("http://localhost:8080/health", timeout=2)
        vllm_status = "connected" if response.status_code == 200 else "disconnected"
    except:
        vllm_status = "disconnected"

    # Check Ollama connection
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=2)
        ollama_status = "connected" if response.status_code == 200 else "disconnected"
    except:
        ollama_status = "disconnected"

    # Display status
    vllm_color = "connected" if vllm_status == "connected" else "disconnected"
    ollama_color = "connected" if ollama_status == "connected" else "disconnected"

    st.markdown(f"""
    <div style="padding: 0.5rem;">
        <div><span class="status-indicator status-{vllm_color}"></span> vLLM Metrics (port 8080)</div>
        <div><span class="status-indicator status-{ollama_color}"></span> Ollama AI (port 11434)</div>
    </div>
    """, unsafe_allow_html=True)

    if vllm_status == "disconnected":
        st.error("⚠️ vLLM not connected. Run port-forward.")

    if ollama_status == "disconnected":
        st.warning("⚠️ Ollama not running. AI insights unavailable.")
        with st.expander("How to start Ollama"):
            st.code("""
# Start Ollama
ollama serve

# Pull Granite model
ollama pull granite3-dense:8b
            """)

    st.markdown("---")
    st.markdown("#### 📖 Help")
    st.markdown("[Documentation](https://github.com/yuvalluria/Ai-observability-insights)")
    st.markdown("[Report Issue](https://github.com/yuvalluria/Ai-observability-insights/issues)")
