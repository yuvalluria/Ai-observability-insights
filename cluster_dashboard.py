#!/usr/bin/env python3
"""
Cluster Dashboard - vLLM Cluster-Wide Monitoring
Shows aggregated metrics across all vLLM services in the cluster
"""

import streamlit as st
import time
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
from prometheus_client import PrometheusClient
from vllm_metrics_scraper import VLLMMetricsScraper
from cluster_client import OpenShiftClusterClient
import json

# Page config
st.set_page_config(
    page_title="vLLM Cluster Dashboard",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS matching RHOAI Perses style
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .cluster-info-banner {
        background: #f0f2f6;
        padding: 0.75rem 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
    .stat-card {
        background: white;
        padding: 1.5rem;
        border-radius: 0.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .stat-card-healthy {
        border-left: 4px solid #28a745;
    }
    .stat-card-warning {
        border-left: 4px solid #ffc107;
    }
    .stat-card-critical {
        border-left: 4px solid #dc3545;
    }
    .service-table {
        margin-top: 1rem;
    }
    .alert-banner {
        padding: 1.5rem;
        border-radius: 0.75rem;
        margin-bottom: 1.5rem;
        font-size: 1.1rem;
        line-height: 1.6;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .alert-critical {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        color: white;
        border-left: 6px solid #c41e3a;
    }
    .alert-warning {
        background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%);
        color: #333;
        border-left: 6px solid #ff8c42;
    }
    .alert-info {
        background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
        color: #333;
        border-left: 6px solid #4facfe;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'cluster_client' not in st.session_state:
    st.session_state.cluster_client = OpenShiftClusterClient()
if 'prometheus_client' not in st.session_state:
    st.session_state.prometheus_client = PrometheusClient(
        cluster_client=st.session_state.cluster_client
    )
if 'vllm_scraper' not in st.session_state:
    st.session_state.vllm_scraper = VLLMMetricsScraper(
        vllm_url="http://localhost:8080",
        cluster_client=st.session_state.cluster_client
    )
if 'discovered_services' not in st.session_state:
    st.session_state.discovered_services = []
if 'cluster_insight' not in st.session_state:
    st.session_state.cluster_insight = None
if 'last_cluster_analysis' not in st.session_state:
    st.session_state.last_cluster_analysis = 0


def query_ollama_cluster(cluster_metrics, services_metrics):
    """Generate cluster-level AI insights"""
    import requests
    from prompts_v2 import get_cluster_dashboard_prompt

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
            return result.get('response', 'No analysis generated')
        else:
            return "INFO: Cluster metrics collected. AI analysis temporarily unavailable."
    except:
        return "INFO: Cluster metrics collected. AI analysis temporarily unavailable."


def get_severity_class(text):
    """Extract severity from AI response"""
    text_upper = text.upper()
    if 'CRITICAL' in text_upper:
        return 'alert-critical', 'CRITICAL'
    elif 'WARNING' in text_upper:
        return 'alert-warning', 'WARNING'
    else:
        return 'alert-info', 'INFO'


# Sidebar
with st.sidebar:
    st.markdown("### Cluster Dashboard")

    # Check cluster connection
    if st.session_state.cluster_client.is_logged_in():
        st.success("Connected to OpenShift")

        if st.button("Discover Services", use_container_width=True):
            with st.spinner("Discovering vLLM services..."):
                st.session_state.discovered_services = st.session_state.cluster_client.discover_vllm_services()
                st.rerun()
    else:
        st.warning("Not logged in to cluster")
        st.info("Run: `oc login <cluster-url>` to enable service discovery")

    # Check Prometheus connection
    prometheus_available = st.session_state.prometheus_client.is_available()

    if prometheus_available:
        st.success("Connected to Prometheus")
    else:
        st.warning("Prometheus unavailable")

    st.markdown("---")
    st.markdown("### Navigation")

    if st.button("← Single Service View", use_container_width=True):
        st.switch_page("app.py")

    st.markdown("---")
    st.markdown(f"**Last Discovery:** {len(st.session_state.discovered_services)} services")


# Main header
st.markdown('<div class="main-header">vLLM Cluster Dashboard</div>', unsafe_allow_html=True)

# Get cluster resource summary
cluster_resources = st.session_state.cluster_client.get_cluster_resource_summary()

# Cluster info banner with clarification
st.markdown(f"""
<div class="cluster-info-banner">
    <strong>Cluster Resources:</strong> {cluster_resources['ready_nodes']}/{cluster_resources['total_nodes']} nodes ready |
    {cluster_resources['total_gpus']} GPUs |
    {cluster_resources['total_cpu_cores']} CPU cores |
    {cluster_resources['total_memory_gb']:.0f}GB system RAM<br>
    <small><em>Note: System RAM is node memory for Kubernetes scheduling. GPU VRAM (e.g., 24GB on A10G) is separate.</em></small>
</div>
""", unsafe_allow_html=True)

# Get cluster metrics from direct vLLM connection (simplified for single service)
if st.session_state.vllm_scraper.is_available():
    # Get metrics from direct vLLM connection
    vllm_metrics = st.session_state.vllm_scraper.get_metrics()

    # Adapt single-service metrics to cluster format
    cluster_metrics = {
        'total_models': 1,  # Single model connected
        'avg_gpu_utilization': vllm_metrics.get('kv_cache_usage_perc', 0),
        'cluster_throughput': vllm_metrics.get('tokens_per_second', 0),
        'cluster_success_rate': vllm_metrics.get('request_success_rate', 100.0),
        'total_requests_running': vllm_metrics.get('num_requests_running', 0),
        'total_requests_waiting': vllm_metrics.get('num_requests_waiting', 0),
        'avg_latency_p90': vllm_metrics.get('e2e_request_latency_p90', 0.0)
    }
else:
    # Fall back to Prometheus if available
    cluster_metrics = st.session_state.prometheus_client.get_cluster_metrics()

st.markdown("---")

# Top stats cards (matching RHOAI Perses layout)
st.markdown("### Cluster Overview")

stat_cols = st.columns(4)

with stat_cols[0]:
    health_ratio = cluster_resources['health_ratio'] * 100
    health_class = "stat-card-healthy" if health_ratio >= 90 else "stat-card-warning" if health_ratio >= 75 else "stat-card-critical"

    st.markdown(f'<div class="stat-card {health_class}">', unsafe_allow_html=True)
    st.metric("System Health", f"{health_ratio:.0f}%", help=f"{cluster_resources['ready_nodes']}/{cluster_resources['total_nodes']} nodes ready")
    st.markdown('</div>', unsafe_allow_html=True)

with stat_cols[1]:
    st.markdown('<div class="stat-card stat-card-healthy">', unsafe_allow_html=True)
    st.metric("Deployed Models", cluster_metrics['total_models'], help="Unique vLLM models across all namespaces")
    st.markdown('</div>', unsafe_allow_html=True)

with stat_cols[2]:
    avg_gpu = cluster_metrics['avg_gpu_utilization']
    gpu_class = "stat-card-critical" if avg_gpu > 90 else "stat-card-warning" if avg_gpu > 75 else "stat-card-healthy"

    st.markdown(f'<div class="stat-card {gpu_class}">', unsafe_allow_html=True)
    st.metric("Avg GPU Utilization", f"{avg_gpu}%", help="Average GPU cache usage across cluster")
    st.markdown('</div>', unsafe_allow_html=True)

with stat_cols[3]:
    success_rate = cluster_metrics['cluster_success_rate']
    success_class = "stat-card-healthy" if success_rate > 98 else "stat-card-warning" if success_rate > 95 else "stat-card-critical"

    st.markdown(f'<div class="stat-card {success_class}">', unsafe_allow_html=True)
    st.metric("Request Success Rate", f"{success_rate}%", help="Cluster-wide request success rate")
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")

# AI Cluster Insights
current_time = time.time()
if st.session_state.cluster_insight is None or current_time - st.session_state.last_cluster_analysis > 120:
    with st.spinner("AI analyzing cluster health..."):
        # Get per-service metrics for outlier detection
        services_metrics = st.session_state.prometheus_client.get_all_services_metrics()

        cluster_insight = query_ollama_cluster(cluster_metrics, services_metrics)
        st.session_state.cluster_insight = cluster_insight
        st.session_state.last_cluster_analysis = current_time

if st.session_state.cluster_insight:
    severity_class, severity_text = get_severity_class(st.session_state.cluster_insight)

    display_text = st.session_state.cluster_insight
    for prefix in ['CRITICAL: ', 'WARNING: ', 'INFO: ']:
        if display_text.startswith(prefix):
            display_text = display_text[len(prefix):]
            break

    st.markdown(f"""
    <div class="alert-banner {severity_class}">
        <strong>Cluster AI Insight</strong><br/>
        {display_text}
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# Cluster-wide resource trends
st.markdown("### Cluster Resource Trends")

trend_cols = st.columns(3)

with trend_cols[0]:
    st.metric("Cluster Throughput", f"{cluster_metrics['cluster_throughput']} tok/s",
              help="Total tokens/sec across all services")

with trend_cols[1]:
    st.metric("Requests Running", cluster_metrics['total_requests_running'],
              help="Total concurrent requests across cluster")

with trend_cols[2]:
    st.metric("Requests Waiting", cluster_metrics['total_requests_waiting'],
              help="Total queued requests across cluster")

st.markdown("---")

# Resource usage by namespace
st.markdown("### Resource Usage by Project/Namespace")

namespace_data = st.session_state.prometheus_client.get_metrics_by_namespace()

if namespace_data and len(namespace_data) > 0:
    ns_df = pd.DataFrame(namespace_data)

    # If only 1-2 namespaces, show as simple table/metrics, not charts
    if len(ns_df) <= 2:
        st.caption(f"Showing {len(ns_df)} namespace(s). Charts appear when 3+ namespaces are deployed.")

        for _, row in ns_df.iterrows():
            ns_name = row['namespace']
            gpu = row.get('gpu_utilization', 0)
            throughput = row.get('throughput', 0)

            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.markdown(f"**{ns_name}**")
            with col2:
                st.metric("GPU Utilization", f"{gpu}%")
            with col3:
                st.metric("Throughput", f"{throughput} tok/s")

            st.markdown("---")
    else:
        # 3+ namespaces: Show bar charts for comparison
        col1, col2 = st.columns(2)

        with col1:
            # GPU utilization by namespace
            fig_gpu = go.Figure()
            fig_gpu.add_trace(go.Bar(
                x=ns_df['namespace'],
                y=ns_df['gpu_utilization'],
                marker_color='#636EFA',
                name='GPU Utilization %'
            ))
            fig_gpu.update_layout(
                title="GPU Utilization by Namespace",
                xaxis_title="Namespace",
                yaxis_title="GPU Utilization (%)",
                height=300,
                showlegend=False
            )
            st.plotly_chart(fig_gpu, use_container_width=True)

        with col2:
            # Throughput by namespace
            if 'throughput' in ns_df.columns:
                fig_throughput = go.Figure()
                fig_throughput.add_trace(go.Bar(
                    x=ns_df['namespace'],
                    y=ns_df['throughput'],
                    marker_color='#EF553B',
                    name='Throughput (tok/s)'
                ))
                fig_throughput.update_layout(
                    title="Throughput by Namespace",
                    xaxis_title="Namespace",
                    yaxis_title="Tokens/Second",
                    height=300,
                    showlegend=False
                )
                st.plotly_chart(fig_throughput, use_container_width=True)
else:
    st.info("No namespace-level metrics available. Deploy vLLM services to see breakdown.")

st.markdown("---")

# Model deployments table
st.markdown("### Model Deployments")

# Auto-detect connected vLLM service via port-forward
if st.session_state.vllm_scraper.is_available():
    # Get current service info from direct connection
    vllm_metrics = st.session_state.vllm_scraper.get_metrics()

    # Show the currently connected service
    connected_services = [{
        'name': 'vllm-llama-model-predictor',  # Known from earlier discovery
        'namespace': vllm_metrics.get('namespace', 'lightspeed-poc'),
        'model': vllm_metrics.get('model_name', 'unknown'),
        'gpu': vllm_metrics.get('gpu_type', 'Unknown GPU'),
        'requests_running': vllm_metrics.get('num_requests_running', 0),
        'requests_waiting': vllm_metrics.get('num_requests_waiting', 0),
        'kv_cache_usage': f"{vllm_metrics.get('kv_cache_usage_perc', 0)}%",
        'status': '✅ Connected'
    }]

    services_df = pd.DataFrame(connected_services)

    # Display table with live metrics
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
            'kv_cache_usage': st.column_config.TextColumn('KV Cache', width='small'),
            'status': st.column_config.TextColumn('Status', width='small')
        }
    )

    st.success(f"Connected to vLLM service via port-forward (localhost:8080)")
elif st.session_state.discovered_services:
    # Fall back to discovered services from cluster scan
    services_df = pd.DataFrame(st.session_state.discovered_services)

    # Display table
    st.dataframe(
        services_df[['name', 'namespace', 'model', 'replicas', 'ready_replicas']],
        use_container_width=True,
        hide_index=True
    )

    # Add drill-down capability
    st.caption("Click 'Single Service View' in sidebar to monitor individual services")
else:
    st.info("No vLLM services detected. Make sure port-forward is running: `oc port-forward -n lightspeed-poc pod/<pod-name> 8080:8080`")

# Auto-refresh
st.markdown("---")
st.caption("Auto-refreshing every 30 seconds...")
time.sleep(30)
st.rerun()
