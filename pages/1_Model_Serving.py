"""
Model Serving Dashboard - RHOAI vLLM Monitoring
Real-time metrics and AI-powered insights for individual vLLM deployments
"""

import streamlit as st
import sys
import os
import time
import requests
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.metrics_service import MetricsService
from shared.components import *
from cluster_client import OpenShiftClusterClient
from bottleneck_classifier import classify_bottleneck_type, get_severity_from_category, get_diagnostic_summary, get_recommendation
from metrics_db import MetricsDatabase

# Page config
st.set_page_config(
    page_title="Model Serving Monitor",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'cluster_client' not in st.session_state:
    st.session_state.cluster_client = OpenShiftClusterClient()

if 'metrics_service' not in st.session_state:
    st.session_state.metrics_service = MetricsService(
        vllm_url="http://localhost:8080",
        cluster_client=st.session_state.cluster_client
    )

if 'metrics_db' not in st.session_state:
    st.session_state.metrics_db = MetricsDatabase()

if 'messages' not in st.session_state:
    st.session_state.messages = []

if 'latest_insight' not in st.session_state:
    st.session_state.latest_insight = None

if 'last_analysis_time' not in st.session_state:
    st.session_state.last_analysis_time = 0


def query_ollama_analysis(metrics, category, diagnostic):
    """Generate AI analysis using Ollama"""
    import requests
    from prompts_v2 import get_model_serving_auto_analysis_prompt_direct

    # Add category and diagnostic to metrics for prompt
    metrics_with_context = metrics.copy()
    metrics_with_context['bottleneck_category'] = category
    metrics_with_context['diagnostic'] = diagnostic

    prompt = get_model_serving_auto_analysis_prompt_direct(metrics_with_context)

    try:
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                'model': 'granite3-dense:8b',
                'prompt': prompt,
                'stream': False
            },
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            return result.get('response', 'No analysis generated')
        else:
            return None
    except:
        return None


# Main header
st.markdown('<div class="main-header">Model Serving Monitor</div>', unsafe_allow_html=True)

# Connection status
vllm_available = st.session_state.metrics_service.is_available()

try:
    ollama_response = requests.get("http://localhost:11434/api/tags", timeout=2)
    ollama_available = ollama_response.status_code == 200
except:
    ollama_available = False

render_connection_status(vllm_available, ollama_available)

st.markdown("---")

# Get current metrics
if vllm_available:
    current_metrics = st.session_state.metrics_service.get_metrics()

    # Save to database
    st.session_state.metrics_db.save_metrics(
        cluster_name="rhoai-vllm",
        metrics=current_metrics
    )

    # Display GPU and model info
    st.markdown(f"""
    **Model:** `{current_metrics['model_name']}` | **GPU:** `{current_metrics['gpu_type']}` | **Source:** `{current_metrics['source']}`
    """)

    st.markdown("---")

    # Key Metrics (RHOAI 8 metrics)
    st.markdown("### 📊 Core Metrics (RHOAI)")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        gpu_util = current_metrics['gpu_utilization']
        gpu_color = "red" if gpu_util > 90 else "orange" if gpu_util > 75 else "green"
        render_metric_card(
            "GPU Utilization",
            f"{gpu_util}%",
            help_text="GPU compute usage (DCGM metric)",
            color=gpu_color
        )

    with col2:
        kv_cache = current_metrics['kv_cache_usage_perc']
        kv_color = "red" if kv_cache > 85 else "orange" if kv_cache > 70 else "green"
        render_metric_card(
            "GPU Memory (KV Cache)",
            f"{kv_cache}%",
            help_text="GPU memory usage approximation",
            color=kv_color
        )

    with col3:
        running = current_metrics['num_requests_running']
        waiting = current_metrics['num_requests_waiting']
        queue_color = "red" if waiting > 5 else "orange" if waiting > 2 else "blue"
        render_metric_card(
            "Requests (Running/Waiting)",
            f"{running} / {waiting}",
            help_text="Active and queued requests",
            color=queue_color
        )

    with col4:
        success_rate = current_metrics['request_success_rate']
        success_color = "green" if success_rate > 98 else "orange" if success_rate > 95 else "red"
        render_metric_card(
            "Success Rate",
            f"{success_rate}%",
            delta=f"Error: {current_metrics['request_failure_rate']}%",
            help_text="Request success rate",
            color=success_color
        )

    st.markdown("---")

    # Latency Metrics
    st.markdown("### ⏱️ Latency Metrics")

    col1, col2, col3 = st.columns(3)

    with col1:
        e2e_latency = current_metrics['e2e_request_latency_p90']
        latency_color = "red" if e2e_latency > 10 else "orange" if e2e_latency > 5 else "blue"
        render_metric_card(
            "E2E Latency (P90)",
            f"{e2e_latency:.2f}s",
            help_text="End-to-end request latency",
            color=latency_color
        )

    with col2:
        ttft = current_metrics['time_to_first_token_p90']
        ttft_color = "red" if ttft > 2 else "orange" if ttft > 1 else "blue"
        render_metric_card(
            "TTFT (P90)",
            f"{ttft:.2f}s",
            help_text="Time to first token (prefill speed)",
            color=ttft_color
        )

    with col3:
        throughput = current_metrics['tokens_per_second']
        render_metric_card(
            "Throughput",
            f"{throughput} tok/s" if throughput > 0 else "Calculating...",
            help_text="Total tokens per second",
            color="blue"
        )

    st.markdown("---")

    # AI-Powered Insights
    st.markdown("### 🤖 AI-Powered Insights")

    if not ollama_available:
        st.error("⚠️ **Ollama not running** - AI insights unavailable. Start Ollama: `ollama serve`")
        with st.expander("How to setup Ollama"):
            st.code("""
# Install Ollama
brew install ollama  # macOS

# Start Ollama
ollama serve &

# Pull Granite model
ollama pull granite3-dense:8b
            """)
    else:
        # Run bottleneck classification
        category = classify_bottleneck_type(current_metrics)
        severity = get_severity_from_category(category, current_metrics)
        diagnostic = get_diagnostic_summary(category, current_metrics)
        recommendation = get_recommendation(category, current_metrics)

        # Check if we need new AI analysis (every 2 minutes)
        current_time = time.time()
        if st.session_state.latest_insight is None or current_time - st.session_state.last_analysis_time > 120:
            with st.spinner("AI analyzing metrics..."):
                ai_analysis = query_ollama_analysis(current_metrics, category, diagnostic)
                if ai_analysis:
                    st.session_state.latest_insight = ai_analysis
                    st.session_state.last_analysis_time = current_time

        # Display insight
        if st.session_state.latest_insight:
            severity_lower = severity.lower()
            render_alert_banner(
                severity=severity_lower,
                title=f"{severity}: {category.replace('_', ' ').title()}",
                message=diagnostic,
                show_expand=True,
                expanded_content=st.session_state.latest_insight
            )
        else:
            # Fallback to Python diagnostic
            severity_lower = severity.lower()
            render_alert_banner(
                severity=severity_lower,
                title=f"{severity}: {category.replace('_', ' ').title()}",
                message=diagnostic
            )

        # Show recommendations
        if recommendation:
            render_commands_section([{
                'description': recommendation['action'],
                'command': '\n'.join(recommendation['steps']),
                'expected': recommendation['expected_improvement'],
                'risk': 'Low - Rolling update',
                'verify': "Watch metrics for changes"
            }])

    st.markdown("---")

    # Charts with progressive disclosure
    with st.expander("📈 Historical Trends", expanded=False):
        timestamps = st.session_state.metrics_service.timestamps
        history = st.session_state.metrics_service.history

        if timestamps and len(timestamps) > 1:
            col1, col2 = st.columns(2)

            with col1:
                if 'gpu_utilization' in history:
                    render_metric_chart(
                        title="GPU Utilization Over Time",
                        timestamps=timestamps,
                        values=history['gpu_utilization'],
                        threshold=85,
                        threshold_label="High Usage (85%)",
                        y_label="GPU %",
                        color="#3b82f6"
                    )

            with col2:
                if 'num_requests_running' in history:
                    render_metric_chart(
                        title="Requests Running",
                        timestamps=timestamps,
                        values=history['num_requests_running'],
                        y_label="Count",
                        color="#10b981"
                    )

            col3, col4 = st.columns(2)

            with col3:
                if 'e2e_request_latency_p90' in history:
                    render_metric_chart(
                        title="E2E Latency (P90)",
                        timestamps=timestamps,
                        values=history['e2e_request_latency_p90'],
                        threshold=10.0,
                        threshold_label="SLO Target (10s)",
                        y_label="Seconds",
                        color="#f59e0b"
                    )

            with col4:
                if 'time_to_first_token_p90' in history:
                    render_metric_chart(
                        title="TTFT (P90)",
                        timestamps=timestamps,
                        values=history['time_to_first_token_p90'],
                        threshold=2.0,
                        threshold_label="Target (2s)",
                        y_label="Seconds",
                        color="#ef4444"
                    )
        else:
            st.info("Collecting data... Check back in 30 seconds for trends.")

    # Interactive Chat (collapsed by default)
    with st.expander("💬 Ask AI About Metrics", expanded=False):
        if not ollama_available:
            st.warning("Ollama required for chat. Start Ollama first.")
        else:
            # Display chat history
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            # Chat input
            if prompt := st.chat_input("Ask about the metrics..."):
                st.session_state.messages.append({"role": "user", "content": prompt})

                with st.chat_message("user"):
                    st.markdown(prompt)

                with st.chat_message("assistant"):
                    with st.spinner("Thinking..."):
                        from prompts_v2 import get_model_serving_chat_prompt

                        chat_prompt = get_model_serving_chat_prompt(current_metrics, prompt)

                        try:
                            response = requests.post(
                                'http://localhost:11434/api/generate',
                                json={
                                    'model': 'granite3-dense:8b',
                                    'prompt': chat_prompt,
                                    'stream': False
                                },
                                timeout=30
                            )

                            if response.status_code == 200:
                                result = response.json()
                                ai_response = result.get('response', 'No response')
                                st.markdown(ai_response)
                                st.session_state.messages.append({"role": "assistant", "content": ai_response})
                            else:
                                st.error("AI service error")
                        except Exception as e:
                            st.error(f"Error: {e}")

else:
    render_empty_state(
        "vLLM not connected. Run port-forward to start monitoring.",
        "🔌"
    )
    st.code("oc port-forward -n <namespace> pod/<vllm-pod-name> 8080:8080")

# Auto-refresh every 30 seconds
time.sleep(30)
st.rerun()
