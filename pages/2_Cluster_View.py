"""
Cluster View Dashboard - RHOAI Multi-Service Monitoring
Aggregate metrics and insights across all vLLM deployments in the cluster
"""

import streamlit as st
import sys
import os
import time
import requests
import pandas as pd
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.metrics_service import MetricsService
from shared.components import *
from cluster_client import OpenShiftClusterClient

# Page config
st.set_page_config(
    page_title="Cluster View",
    page_icon="🌐",
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

if 'discovered_services' not in st.session_state:
    st.session_state.discovered_services = []


# Main header
st.markdown('<div class="main-header">Cluster Overview</div>', unsafe_allow_html=True)

# Connection status
vllm_available = st.session_state.metrics_service.is_available()

try:
    ollama_response = requests.get("http://localhost:11434/api/tags", timeout=2)
    ollama_available = ollama_response.status_code == 200
except:
    ollama_available = False

render_connection_status(vllm_available, ollama_available)

st.markdown("---")

# Cluster Resource Summary
if st.session_state.cluster_client.is_logged_in():
    cluster_resources = st.session_state.cluster_client.get_cluster_resource_summary()

    st.markdown(f"""
    **Cluster Resources:** {cluster_resources['ready_nodes']}/{cluster_resources['total_nodes']} nodes ready |
    {cluster_resources['total_gpus']} GPUs |
    {cluster_resources['total_cpu_cores']} CPU cores |
    {cluster_resources['total_memory_gb']:.0f}GB system RAM
    """)

    st.caption("_Note: System RAM is node memory for Kubernetes scheduling. GPU VRAM (e.g., 24GB on A10G) is separate._")
else:
    st.info("Not logged in to cluster. Run: `oc login <cluster-url>` for cluster-wide monitoring.")

st.markdown("---")

# Connected Services
st.markdown("### 📡 vLLM Services")

if vllm_available:
    # Get metrics from connected service
    vllm_metrics = st.session_state.metrics_service.get_metrics()

    # Display connected service
    service_data = [{
        'name': 'vllm-service',
        'namespace': vllm_metrics['namespace'],
        'model': vllm_metrics['model_name'],
        'gpu': vllm_metrics['gpu_type'],
        'requests_running': vllm_metrics['num_requests_running'],
        'requests_waiting': vllm_metrics['num_requests_waiting'],
        'gpu_util': f"{vllm_metrics['gpu_utilization']}%",
        'success_rate': f"{vllm_metrics['request_success_rate']}%",
        'status': '✅ Connected'
    }]

    services_df = pd.DataFrame(service_data)

    st.dataframe(
        services_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            'name': st.column_config.TextColumn('Service Name', width='medium'),
            'namespace': st.column_config.TextColumn('Namespace', width='small'),
            'model': st.column_config.TextColumn('Model', width='medium'),
            'gpu': st.column_config.TextColumn('GPU Type', width='medium'),
            'requests_running': st.column_config.NumberColumn('Running', width='small'),
            'requests_waiting': st.column_config.NumberColumn('Waiting', width='small'),
            'gpu_util': st.column_config.TextColumn('GPU %', width='small'),
            'success_rate': st.column_config.TextColumn('Success', width='small'),
            'status': st.column_config.TextColumn('Status', width='small')
        }
    )

    st.success(f"✅ Connected to vLLM service via port-forward (localhost:8080)")

    st.markdown("---")

    # Cluster-Level Metrics (from single service - simplified)
    st.markdown("### 📊 Service Performance")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        render_metric_card(
            "Total Requests",
            f"{vllm_metrics['num_requests_running']}",
            delta=f"{vllm_metrics['num_requests_waiting']} waiting",
            help_text="Active and queued requests",
            color="blue"
        )

    with col2:
        avg_gpu = vllm_metrics['gpu_utilization']
        gpu_color = "red" if avg_gpu > 90 else "orange" if avg_gpu > 75 else "green"
        render_metric_card(
            "GPU Utilization",
            f"{avg_gpu}%",
            help_text="GPU compute usage",
            color=gpu_color
        )

    with col3:
        throughput = vllm_metrics['tokens_per_second']
        render_metric_card(
            "Throughput",
            f"{throughput} tok/s" if throughput > 0 else "Calculating...",
            help_text="Tokens per second",
            color="blue"
        )

    with col4:
        success_rate = vllm_metrics['request_success_rate']
        success_color = "green" if success_rate > 98 else "orange" if success_rate > 95 else "red"
        render_metric_card(
            "Success Rate",
            f"{success_rate}%",
            delta=f"{vllm_metrics['request_failure_rate']}% error",
            help_text="Request success rate",
            color=success_color
        )

    st.markdown("---")

    # Performance Trends
    st.markdown("### 📈 Performance Trends")

    timestamps = st.session_state.metrics_service.timestamps
    history = st.session_state.metrics_service.history

    if timestamps and len(timestamps) > 1:
        col1, col2 = st.columns(2)

        with col1:
            if 'gpu_utilization' in history:
                render_metric_chart(
                    title="GPU Utilization Trend",
                    timestamps=timestamps,
                    values=history['gpu_utilization'],
                    threshold=85,
                    threshold_label="High (85%)",
                    y_label="GPU %",
                    color="#3b82f6"
                )

        with col2:
            if 'e2e_request_latency_p90' in history:
                render_metric_chart(
                    title="E2E Latency (P90)",
                    timestamps=timestamps,
                    values=history['e2e_request_latency_p90'],
                    threshold=10.0,
                    threshold_label="SLO (10s)",
                    y_label="Seconds",
                    color="#f59e0b"
                )
    else:
        st.info("Collecting trend data... Check back in 30 seconds.")

    # AI Cluster Insights (if Ollama available)
    if ollama_available:
        st.markdown("---")
        st.markdown("### 🤖 AI Cluster Insights")

        with st.spinner("AI analyzing cluster health..."):
            from prompts_v2 import get_cluster_dashboard_prompt

            cluster_metrics = {
                'total_models': 1,
                'avg_gpu_utilization': vllm_metrics['gpu_utilization'],
                'cluster_throughput': vllm_metrics['tokens_per_second'],
                'cluster_success_rate': vllm_metrics['request_success_rate'],
                'total_requests_running': vllm_metrics['num_requests_running'],
                'total_requests_waiting': vllm_metrics['num_requests_waiting']
            }

            services_metrics = [vllm_metrics]

            prompt = get_cluster_dashboard_prompt(cluster_metrics, services_metrics)

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
                    ai_insight = result.get('response', 'No analysis generated')

                    # Determine severity
                    severity = "info"
                    if "CRITICAL" in ai_insight.upper():
                        severity = "critical"
                    elif "WARNING" in ai_insight.upper():
                        severity = "warning"

                    render_alert_banner(
                        severity=severity,
                        title="Cluster AI Insight",
                        message=ai_insight
                    )
            except Exception as e:
                st.error(f"AI analysis failed: {e}")

else:
    render_empty_state(
        "No vLLM services connected. Run port-forward to monitor cluster.",
        "🔌"
    )
    st.code("oc port-forward -n <namespace> pod/<vllm-pod-name> 8080:8080")

# Sidebar - Service Discovery
with st.sidebar:
    st.markdown("### 🔍 Service Discovery")

    if st.session_state.cluster_client.is_logged_in():
        if st.button("🔄 Discover All Services", use_container_width=True):
            with st.spinner("Scanning cluster..."):
                st.session_state.discovered_services = st.session_state.cluster_client.discover_vllm_services()
                st.rerun()

        if st.session_state.discovered_services:
            st.success(f"Found {len(st.session_state.discovered_services)} services")
            for svc in st.session_state.discovered_services:
                st.caption(f"- {svc['name']} ({svc['namespace']})")
    else:
        st.info("Login to OpenShift to discover all cluster services")

# Auto-refresh every 30 seconds
time.sleep(30)
st.rerun()
