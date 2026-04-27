import streamlit as st
import json
import time
import random
from datetime import datetime, timedelta
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from prometheus_client import PrometheusClient
from metrics_db import MetricsDatabase

# Page config
st.set_page_config(
    page_title="AI Observability Insighter",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
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
    .metric-card-critical {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%) !important;
        color: white !important;
    }
    .metric-card-warning {
        background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%) !important;
        color: #333 !important;
    }
    .metric-card-healthy {
        background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%) !important;
        color: #333 !important;
    }
    .stChatMessage {
        background-color: #f0f2f6;
        border-radius: 0.5rem;
        padding: 1rem;
        margin: 0.5rem 0;
    }
    div[data-testid="metric-container"] {
        padding: 1rem;
        border-radius: 0.5rem;
    }
    .floating-chat-button {
        position: fixed;
        bottom: 20px;
        right: 20px;
        z-index: 1000;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        width: 60px;
        height: 60px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        cursor: pointer;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        transition: transform 0.2s;
    }
    .floating-chat-button:hover {
        transform: scale(1.1);
    }
    .export-button {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        border: none;
        cursor: pointer;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

class MetricsSimulator:
    def __init__(self):
        self.base_metrics = {
            "kv_cache_usage_perc": 45,  # KV cache memory usage
            "gpu_compute_utilization": 70,  # GPU compute utilization
            "gpu_utilization": 45,  # Legacy field (same as kv_cache)
            "gpu_type": "NVIDIA A10G (24GB)",
            "gpu_architecture": "Ampere",
            "cuda_version": "13.0",
            "compute_capability": "8.6",
            "batch_size": None,  # Not explicitly configured
            "max_num_seqs": None,
            "num_requests_running": 5,
            "num_requests_waiting": 2,
            "request_failure_rate": 2.0,
            "request_success_rate": 98.0,
            "e2e_request_latency_p90": 2.5,
            "time_to_first_token_p90": 0.8,
            "tokens_per_second": 200,
            "requests_per_second": 15,
            "replica_count": 2,
            "namespace": "rhoai-granite-8b",
            "model_name": "granite-8b-code-instruct",
            "cpu_utilization_pct": 55,
            "prompt_tokens_total": 8192,
            "generation_tokens_total": 12288,
            "prompt_tokens_p50": 128,
            "prompt_tokens_p90": 256,
            "prompt_tokens_p99": 512,
            "generation_tokens_p50": 64,
            "generation_tokens_p90": 128,
            "generation_tokens_p99": 256
        }
        self.history = {key: [] for key in self.base_metrics.keys()}
        self.timestamps = []

    def generate_metrics(self):
        """Generate simulated metrics with realistic variations"""
        current = {}
        for key, base_value in self.base_metrics.items():
            if isinstance(base_value, str):
                current[key] = base_value
            elif isinstance(base_value, int):
                if key in ['replica_count']:
                    current[key] = base_value
                else:
                    variation = random.randint(-10, 10)
                    current[key] = max(0, base_value + variation)
            else:  # float
                variation = random.uniform(-0.3, 0.3)
                current[key] = max(0, round(base_value + variation, 2))

        # Update history
        self.timestamps.append(datetime.now().strftime("%H:%M:%S"))
        for key, value in current.items():
            if key not in ['namespace', 'model_name']:
                self.history[key].append(value)

        # Keep only last 15 data points
        if len(self.timestamps) > 15:
            self.timestamps = self.timestamps[-15:]
            for key in self.history:
                self.history[key] = self.history[key][-15:]

        return current

def check_thresholds(metrics):
    """Check if any metrics breach critical thresholds"""
    critical = []
    warning = []

    # Check KV cache usage (memory pressure)
    kv_cache = metrics.get('kv_cache_usage_perc', metrics.get('gpu_utilization', 0))
    if kv_cache > 85:
        critical.append(f"KV cache at {kv_cache}%")
    elif kv_cache > 70:
        warning.append(f"KV cache at {kv_cache}%")

    # Check GPU compute utilization
    gpu_compute = metrics.get('gpu_compute_utilization', 0)
    if gpu_compute > 90:
        warning.append(f"GPU compute at {gpu_compute}%")
    elif gpu_compute > 70:
        # High GPU compute is often good (means busy), only warn if also have queue
        if metrics.get('num_requests_waiting', 0) > 5:
            warning.append(f"GPU compute at {gpu_compute}% with queue buildup")

    if metrics['request_failure_rate'] > 5:
        critical.append(f"Failure rate at {metrics['request_failure_rate']}%")
    elif metrics['request_failure_rate'] > 2:
        warning.append(f"Failure rate at {metrics['request_failure_rate']}%")

    if metrics['e2e_request_latency_p90'] > 5:
        critical.append(f"Latency at {metrics['e2e_request_latency_p90']}s")
    elif metrics['e2e_request_latency_p90'] > 3:
        warning.append(f"Latency at {metrics['e2e_request_latency_p90']}s")

    if metrics['num_requests_waiting'] > 15:
        critical.append(f"{metrics['num_requests_waiting']} requests waiting")
    elif metrics['num_requests_waiting'] > 5:
        warning.append(f"{metrics['num_requests_waiting']} requests waiting")

    if critical:
        return "CRITICAL", critical
    elif warning:
        return "WARNING", warning
    else:
        return "HEALTHY", []

def query_ollama(metrics, user_question, auto=False, models_context=None):
    """
    Hybrid AI approach: Python rules for clear cases, AI for unclear/predictions.

    Flow:
    1. Pre-classify bottleneck (Python rules)
    2. If CLEAR → use Python output + AI prediction
    3. If UNCLEAR → use AI for full analysis
    4. Interactive chat → always use AI
    """
    from prompts_v2 import (
        get_model_serving_auto_analysis_prompt_direct,
        get_model_serving_auto_analysis_prompt_ai,
        get_model_serving_chat_prompt
    )

    if auto:
        # Try pre-classification first
        python_output = get_model_serving_auto_analysis_prompt_direct(metrics, models_context)

        if python_output == "USE_AI_ANALYSIS":
            # Unclear case - use AI for full analysis
            prompt = get_model_serving_auto_analysis_prompt_ai(metrics, models_context)
        else:
            # Clear case - Python got it, but still use AI for predictions
            # Return Python analysis + AI prediction
            prediction_prompt = f"""You are a vLLM expert. Based on these metrics, predict what will happen in the next 10-30 minutes if no action is taken.

CURRENT METRICS:
{json.dumps(metrics, indent=2)}

Provide a brief prediction (2-3 bullet points) focusing on:
- Which metrics will increase/decrease
- Why (traffic patterns, resource saturation, etc.)
- When action becomes necessary

Format:
Prediction (next 10-30 min):
- [Metric]: likely to [change] because [reason]
- [Metric]: likely to [change] because [reason]"""

            try:
                response = requests.post(
                    'http://localhost:11434/api/generate',
                    json={
                        'model': 'granite3-dense:8b',
                        'prompt': prediction_prompt,
                        'stream': False
                    },
                    timeout=30
                )

                if response.status_code == 200:
                    result = response.json()
                    ai_prediction = result.get('response', '')
                    # Combine Python analysis with AI prediction
                    return f"""{python_output}

---

🔮 AI Prediction:
{ai_prediction}"""
                else:
                    # If AI fails, still return Python output
                    return python_output

            except Exception as e:
                # If AI fails, still return Python output
                return python_output
    else:
        # Use LLM for interactive chat
        prompt = get_model_serving_chat_prompt(metrics, user_question)

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
            return result.get('response', 'No response generated')
        else:
            return f"Error: Ollama returned status {response.status_code}"
    except requests.exceptions.ConnectionError:
        return "Error: Cannot connect to Ollama. Make sure Ollama is running (ollama serve)"
    except Exception as e:
        return f"Error: {str(e)}"

def create_metrics_chart(simulator):
    """Create time series charts for key metrics with threshold lines"""
    if len(simulator.timestamps) == 0:
        return None

    fig = make_subplots(
        rows=4, cols=2,
        subplot_titles=(
            'KV Cache vs GPU Compute (%)',
            'Request Failure Rate (%)',
            'E2E Latency P90 (s)',
            'TTFT P90 (s)',
            'Tokens/Second',
            'Request Rate (req/s)',
            'Requests Running/Waiting',
            'Replica Count'
        ),
        vertical_spacing=0.10,
        horizontal_spacing=0.1
    )

    # KV Cache Usage with thresholds
    kv_cache_data = simulator.history.get('kv_cache_usage_perc', simulator.history.get('gpu_utilization', []))
    if kv_cache_data:
        fig.add_trace(
            go.Scatter(x=simulator.timestamps, y=kv_cache_data,
                       mode='lines+markers', name='KV Cache %', line=dict(color='#636EFA')),
            row=1, col=1
        )
    # Add KV cache threshold lines
    fig.add_hline(y=85, line_dash="dash", line_color="red", opacity=0.5, row=1, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="orange", opacity=0.5, row=1, col=1)

    # GPU Compute Utilization
    gpu_compute_data = simulator.history.get('gpu_compute_utilization', [])
    if gpu_compute_data:
        fig.add_trace(
            go.Scatter(x=simulator.timestamps, y=gpu_compute_data,
                       mode='lines+markers', name='GPU Compute %', line=dict(color='#00CC96', dash='dot')),
            row=1, col=1
        )

    # Failure Rate with thresholds
    fig.add_trace(
        go.Scatter(x=simulator.timestamps, y=simulator.history['request_failure_rate'],
                   mode='lines+markers', name='Failure %', line=dict(color='#EF553B')),
        row=1, col=2
    )
    fig.add_hline(y=5, line_dash="dash", line_color="red", opacity=0.5, row=1, col=2)
    fig.add_hline(y=2, line_dash="dash", line_color="orange", opacity=0.5, row=1, col=2)

    # E2E Latency with thresholds
    fig.add_trace(
        go.Scatter(x=simulator.timestamps, y=simulator.history['e2e_request_latency_p90'],
                   mode='lines+markers', name='E2E Latency', line=dict(color='#00CC96')),
        row=2, col=1
    )
    fig.add_hline(y=5, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
    fig.add_hline(y=3, line_dash="dash", line_color="orange", opacity=0.5, row=2, col=1)

    # TTFT P90 with thresholds (NEW)
    ttft_data = simulator.history.get('time_to_first_token_p90', [])
    if ttft_data:
        fig.add_trace(
            go.Scatter(x=simulator.timestamps, y=ttft_data,
                       mode='lines+markers', name='TTFT', line=dict(color='#FECB52')),
            row=2, col=2
        )
        fig.add_hline(y=2, line_dash="dash", line_color="red", opacity=0.5, row=2, col=2)
        fig.add_hline(y=1, line_dash="dash", line_color="orange", opacity=0.5, row=2, col=2)

    # Tokens per second
    fig.add_trace(
        go.Scatter(x=simulator.timestamps, y=simulator.history['tokens_per_second'],
                   mode='lines+markers', name='Tokens/s', line=dict(color='#AB63FA')),
        row=3, col=1
    )

    # Request rate
    fig.add_trace(
        go.Scatter(x=simulator.timestamps, y=simulator.history['requests_per_second'],
                   mode='lines+markers', name='Req/s', line=dict(color='#FF6692')),
        row=3, col=2
    )

    # Requests running/waiting with threshold
    fig.add_trace(
        go.Scatter(x=simulator.timestamps, y=simulator.history['num_requests_running'],
                   mode='lines+markers', name='Running', line=dict(color='#FFA15A')),
        row=4, col=1
    )
    fig.add_trace(
        go.Scatter(x=simulator.timestamps, y=simulator.history['num_requests_waiting'],
                   mode='lines+markers', name='Waiting', line=dict(color='#19D3F3')),
        row=4, col=1
    )
    fig.add_hline(y=15, line_dash="dash", line_color="red", opacity=0.5, row=4, col=1)
    fig.add_hline(y=5, line_dash="dash", line_color="orange", opacity=0.5, row=4, col=1)

    # Replica count
    replica_data = simulator.history.get('replica_count', [])
    if replica_data:
        fig.add_trace(
            go.Scatter(x=simulator.timestamps, y=replica_data,
                       mode='lines+markers', name='Replicas', line=dict(color='#B6E880', width=3)),
            row=4, col=2
        )
        # Add reference line at 1 replica (minimum)
        fig.add_hline(y=1, line_dash="dot", line_color="gray", opacity=0.3, row=4, col=2)

    fig.update_layout(height=1000, showlegend=False, template='plotly_white')
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')

    return fig

def get_severity_class(text):
    """Extract severity from AI response"""
    text_upper = text.upper()
    if 'CRITICAL' in text_upper:
        return 'alert-critical', 'CRITICAL'
    elif 'WARNING' in text_upper:
        return 'alert-warning', 'WARNING'
    else:
        return 'alert-info', 'INFO'

def get_session_id():
    """Generate a stable session ID for tracking feedback across the session"""
    import hashlib
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    ctx = get_script_run_ctx()
    if ctx:
        return hashlib.md5(ctx.session_id.encode()).hexdigest()[:16]
    return "unknown_session"

# Initialize session state
if 'simulator' not in st.session_state:
    st.session_state.simulator = MetricsSimulator()
if 'cluster_client' not in st.session_state:
    from cluster_client import OpenShiftClusterClient
    st.session_state.cluster_client = OpenShiftClusterClient()
if 'prometheus_client' not in st.session_state:
    st.session_state.prometheus_client = PrometheusClient(
        cluster_client=st.session_state.cluster_client
    )
if 'metrics_db' not in st.session_state:
    st.session_state.metrics_db = MetricsDatabase()
if 'use_real_metrics' not in st.session_state:
    st.session_state.use_real_metrics = True  # Default to real metrics
if 'messages' not in st.session_state:
    # Load chat history from database for this session
    loaded_messages = st.session_state.metrics_db.load_chat_history_for_session(
        cluster_name="yluria-vllm-demo",
        session_id=get_session_id(),
        hours=24
    )
    st.session_state.messages = loaded_messages if loaded_messages else []
if 'latest_insight' not in st.session_state:
    st.session_state.latest_insight = None
if 'last_auto_analysis' not in st.session_state:
    st.session_state.last_auto_analysis = 0
if 'show_chat' not in st.session_state:
    st.session_state.show_chat = False
if 'selected_cluster' not in st.session_state:
    st.session_state.selected_cluster = "yluria-vllm-demo"
if 'message_metrics_snapshots' not in st.session_state:
    st.session_state.message_metrics_snapshots = {}  # Store metrics at question time
if 'message_timestamps' not in st.session_state:
    st.session_state.message_timestamps = {}  # Store response times
if 'last_scaling_action' not in st.session_state:
    st.session_state.last_scaling_action = 0  # Timestamp of last scaling recommendation
if 'scaling_cooldown_minutes' not in st.session_state:
    st.session_state.scaling_cooldown_minutes = 5  # Wait 5 minutes between scaling actions
if 'critical_actions_approved' not in st.session_state:
    st.session_state.critical_actions_approved = False  # Require approval for CRITICAL actions
if 'critical_approval_timestamp' not in st.session_state:
    st.session_state.critical_approval_timestamp = 0  # When was CRITICAL action approved
if 'auto_refresh_paused' not in st.session_state:
    st.session_state.auto_refresh_paused = False  # Pause auto-refresh to read content
if 'selected_namespace' not in st.session_state:
    st.session_state.selected_namespace = "All"  # Filter by namespace
if 'selected_model' not in st.session_state:
    st.session_state.selected_model = "All"  # Filter by model
if 'discovered_models' not in st.session_state:
    st.session_state.discovered_models = []  # List of discovered models

# Sidebar
with st.sidebar:
    st.markdown("### Cluster Selection")

    # Cluster selector (ready for multi-cluster support)
    clusters = ["yluria-vllm-demo"]
    selected = st.selectbox(
        "Active Cluster",
        clusters,
        index=0,
        help="Currently monitoring this cluster. Add more clusters in Settings → Prometheus endpoints."
    )
    st.session_state.selected_cluster = selected

    st.markdown("---")
    st.markdown("### Dashboard Views")

    if st.button("Cluster Dashboard →", use_container_width=True, help="View all vLLM services across cluster"):
        st.switch_page("cluster_dashboard.py")

    st.markdown("---")
    st.markdown("### Deployment Info")

    # Check Prometheus connection
    prometheus_available = st.session_state.prometheus_client.is_available()

    if prometheus_available:
        st.success("Connected to Prometheus")
        st.session_state.use_real_metrics = True
    else:
        st.warning("Prometheus unavailable")
        st.info("Demo Mode: Using simulated metrics")
        st.session_state.use_real_metrics = False

    st.markdown(f"""
    **Cluster**: {st.session_state.selected_cluster}
    **Model**: granite-8b-code-instruct
    **Namespace**: lightspeed-poc
    **AI Engine**: Ollama Granite 8B
    """)

    st.markdown("---")
    st.markdown("### Export Data")

    # Export timeframe selector
    export_hours = st.selectbox(
        "Export last",
        [1, 6, 12, 24],
        index=3,
        format_func=lambda x: f"{x} hours"
    )

    # Get data for export
    df_export = st.session_state.metrics_db.get_recent_metrics(
        hours=export_hours,
        cluster_name=st.session_state.selected_cluster
    )

    if not df_export.empty:
        # Select relevant columns for export
        export_df = df_export[[
            'timestamp', 'cluster_name', 'kv_cache_usage',
            'num_requests_running', 'num_requests_waiting',
            'failure_rate', 'latency_p90', 'tokens_per_second',
            'prompt_tokens_total', 'generation_tokens_total'
        ]]

        # Convert to CSV
        csv = export_df.to_csv(index=False)

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"metrics_export_{timestamp}.csv"

        st.download_button(
            label="Export to CSV",
            data=csv,
            file_name=filename,
            mime="text/csv",
            use_container_width=True
        )
        st.caption(f"Ready to download {len(export_df)} data points")
    else:
        st.warning("No data to export")

    st.markdown("---")

    # Auto-refresh control
    if not st.session_state.auto_refresh_paused:
        st.caption("✓ Auto-refresh enabled (every 20 seconds)")
        if st.button("⏸ Pause Auto-Refresh", use_container_width=True):
            st.session_state.auto_refresh_paused = True
            st.rerun()
    else:
        st.caption("⏸ Auto-refresh paused")
        if st.button("▶ Resume Auto-Refresh", use_container_width=True):
            st.session_state.auto_refresh_paused = False
            st.rerun()

# Main header
st.markdown('<div class="main-header">Model Serving Dashboard</div>', unsafe_allow_html=True)
if st.session_state.use_real_metrics:
    st.markdown(f"**Real-time metrics from cluster:** `{st.session_state.selected_cluster}`")
else:
    st.markdown("**Demo Mode** - Using simulated metrics")

# === MODEL DEPLOYMENTS TABLE (Perses style) ===
st.markdown("### Model Deployments")

# Discover all models if not already done or if refresh requested
col_refresh1, col_refresh2 = st.columns([4, 1])
with col_refresh2:
    if st.button("🔄 Discover Models", help="Scan cluster for vLLM deployments"):
        # Comment out login check - dashboard works with Prometheus only
        # if st.session_state.cluster_client.is_logged_in():
        with st.spinner("Discovering models..."):
            st.session_state.discovered_models = st.session_state.cluster_client.discover_vllm_services()
        # else:
        #     st.warning("Not logged in to cluster. Run: `oc login <cluster-url>`")

# Get all services metrics
if st.session_state.use_real_metrics and st.session_state.discovered_models:
    # Query metrics for each discovered model
    models_data = []
    for service in st.session_state.discovered_models:
        try:
            metrics = st.session_state.prometheus_client.get_metrics(
                namespace=service['namespace'],
                service=service['name']
            )

            # Use model name from Prometheus if deployment doesn't have it
            model_name = metrics.get('model_name', service.get('model', 'unknown'))
            if model_name == 'unknown' or model_name == service['name']:
                # Try to get from Prometheus metric
                model_name = metrics.get('model_name', service.get('model', 'unknown'))
            # Calculate smart status based on multiple factors
            latency = metrics.get('e2e_request_latency_p90', 0)
            error_rate = metrics.get('request_failure_rate', 0)
            gpu_usage = metrics.get('kv_cache_usage_perc', metrics.get('gpu_utilization', 0))
            queue = metrics.get('num_requests_waiting', 0)

            # Health scoring
            issues = []
            if error_rate > 5:
                issues.append('high_errors')
            if gpu_usage > 85:
                issues.append('gpu_critical')
            if queue > 15:
                issues.append('queue_critical')
            if latency > 10:
                issues.append('latency_degraded')

            # Determine status
            if issues:
                status = '🔴'  # Critical if any major issue
            elif error_rate > 2 or gpu_usage > 70 or queue > 5 or latency > 5:
                status = '⚠️'  # Warning
            else:
                status = '✅'  # Healthy

            models_data.append({
                'Model': model_name,
                'Namespace': service['namespace'],
                'Replicas': f"{service.get('ready_replicas', 0)}/{service.get('replicas', 0)}",
                'Total Requests': metrics.get('num_requests_running', 0) + metrics.get('num_requests_waiting', 0),
                'P90 Latency': f"{metrics.get('e2e_request_latency_p90', 0)}s",
                'Error Rate': f"{metrics.get('request_failure_rate', 0)}%",
                'GPU %': metrics.get('kv_cache_usage_perc', metrics.get('gpu_utilization', 0)),
                'Throughput': f"{metrics.get('tokens_per_second', 0)} tok/s",
                'Status': status,
                '_namespace': service['namespace'],
                '_model': model_name
            })
        except:
            continue

    if models_data:
        # Create DataFrame
        import pandas as pd
        models_df = pd.DataFrame(models_data)

        # Display table
        st.dataframe(
            models_df[['Model', 'Namespace', 'Replicas', 'Total Requests', 'P90 Latency', 'Error Rate', 'GPU %', 'Throughput', 'Status']],
            use_container_width=True,
            hide_index=True
        )

        # Model/Namespace filter
        col1, col2 = st.columns(2)
        with col1:
            namespaces = ['All'] + sorted(models_df['Namespace'].unique().tolist())
            selected_ns = st.selectbox(
                "Filter by Namespace",
                namespaces,
                index=namespaces.index(st.session_state.selected_namespace) if st.session_state.selected_namespace in namespaces else 0
            )
            st.session_state.selected_namespace = selected_ns

        with col2:
            models = ['All'] + sorted(models_df['Model'].unique().tolist())
            selected_model = st.selectbox(
                "Filter by Model",
                models,
                index=models.index(st.session_state.selected_model) if st.session_state.selected_model in models else 0
            )
            st.session_state.selected_model = selected_model

        # Show filtered metrics based on selection
        if st.session_state.selected_namespace != "All" or st.session_state.selected_model != "All":
            st.info(f"📊 Showing detailed metrics for: {st.session_state.selected_namespace}/{st.session_state.selected_model}")
    else:
        st.info("No vLLM models discovered. Click 'Discover Models' to scan cluster.")
else:
    st.info("Connect to cluster and click 'Discover Models' to see model deployments table.")

st.markdown("---")

# Generate new metrics FIRST (needed by chat)
# If model/namespace selected, get metrics for that specific service
if st.session_state.use_real_metrics:
    if st.session_state.selected_namespace != "All" and st.session_state.selected_model != "All":
        # Get specific model's metrics
        current_metrics = st.session_state.prometheus_client.get_metrics(
            namespace=st.session_state.selected_namespace,
            service=st.session_state.selected_model
        )
    else:
        # Get default service metrics or aggregated
        current_metrics = st.session_state.prometheus_client.get_metrics()
    simulator_for_charts = st.session_state.prometheus_client
else:
    current_metrics = st.session_state.simulator.generate_metrics()
    simulator_for_charts = st.session_state.simulator

# Save metrics to database for historical analysis
st.session_state.metrics_db.save_metrics(
    cluster_name=st.session_state.selected_cluster,
    metrics=current_metrics
)

# Cleanup old data (keep only 24h)
st.session_state.metrics_db.cleanup_old_data()

st.markdown("---")

# === HERO FEATURE: AI CHAT (Move chat to top before everything else) ===
st.markdown("## Ask AI About Your Metrics")
st.caption("Get instant insights and recommendations - powered by Granite 8B")

# Chat interface at the top
chat_container_top = st.container()

with chat_container_top:
    # Display chat messages with feedback buttons
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            # Add feedback buttons ONLY for assistant messages
            if message["role"] == "assistant":
                message_id = f"msg_{idx}"

                # Create unique key for this message's feedback
                feedback_key = f"feedback_{message_id}"

                # Check if feedback already given
                if feedback_key not in st.session_state:
                    st.session_state[feedback_key] = None

                # Display feedback buttons
                col1, col2, col3 = st.columns([1, 1, 10])

                with col1:
                    if st.button("+", key=f"thumbs_up_{message_id}",
                               help="This recommendation was helpful"):
                        # Save feedback to database
                        user_question = st.session_state.messages[idx-1]["content"] if idx > 0 else ""
                        metrics_snapshot = st.session_state.message_metrics_snapshots.get(message_id, {})
                        response_time = st.session_state.message_timestamps.get(message_id, 0)

                        st.session_state.metrics_db.save_feedback(
                            cluster_name=st.session_state.selected_cluster,
                            user_question=user_question,
                            ai_response=message["content"],
                            rating="thumbs_up",
                            metrics_snapshot=metrics_snapshot,
                            session_id=get_session_id(),
                            response_time_ms=int(response_time * 1000) if response_time else None
                        )

                        st.session_state[feedback_key] = "thumbs_up"
                        st.rerun()

                with col2:
                    if st.button("-", key=f"thumbs_down_{message_id}",
                               help="This recommendation was not helpful"):
                        # Save feedback to database
                        user_question = st.session_state.messages[idx-1]["content"] if idx > 0 else ""
                        metrics_snapshot = st.session_state.message_metrics_snapshots.get(message_id, {})
                        response_time = st.session_state.message_timestamps.get(message_id, 0)

                        st.session_state.metrics_db.save_feedback(
                            cluster_name=st.session_state.selected_cluster,
                            user_question=user_question,
                            ai_response=message["content"],
                            rating="thumbs_down",
                            metrics_snapshot=metrics_snapshot,
                            session_id=get_session_id(),
                            response_time_ms=int(response_time * 1000) if response_time else None
                        )

                        st.session_state[feedback_key] = "thumbs_down"
                        st.rerun()

                with col3:
                    # Show feedback status if given
                    if st.session_state[feedback_key] == "thumbs_up":
                        st.caption("✓ Marked as helpful")
                    elif st.session_state[feedback_key] == "thumbs_down":
                        st.caption("✓ Marked as not helpful")

# Chat input with historical context
if prompt := st.chat_input("Ask about metrics, trends, or recommendations..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Save user message to database
    st.session_state.metrics_db.save_chat_message(
        cluster_name=st.session_state.selected_cluster,
        session_id=get_session_id(),
        role="user",
        content=prompt,
        metrics_snapshot=current_metrics
    )

    with st.chat_message("user"):
        st.markdown(prompt)

    # Get AI recommendation with historical context
    with st.chat_message("assistant"):
        with st.spinner("Analyzing..."):
            # Track response time
            start_time = time.time()

            # Check if user is asking about historical data
            historical_keywords = ["ago", "earlier", "before", "past", "history", "previous", "yesterday"]
            needs_history = any(keyword in prompt.lower() for keyword in historical_keywords)

            if needs_history:
                # Get recent data for context
                recent_data = st.session_state.metrics_db.get_recent_metrics(
                    hours=1,
                    cluster_name=st.session_state.selected_cluster
                )
                context = f"\nHistorical Context (last hour): {len(recent_data)} data points collected"
                enhanced_prompt = f"{prompt}\n{context}"
            else:
                enhanced_prompt = prompt

            response = query_ollama(current_metrics, enhanced_prompt)

            # Calculate response time
            response_time = time.time() - start_time

            st.markdown(response)

    # Add assistant message
    st.session_state.messages.append({"role": "assistant", "content": response})

    # Save assistant message to database
    st.session_state.metrics_db.save_chat_message(
        cluster_name=st.session_state.selected_cluster,
        session_id=get_session_id(),
        role="assistant",
        content=response,
        metrics_snapshot=current_metrics
    )

    # Store metrics snapshot and timestamp for this message
    message_id = f"msg_{len(st.session_state.messages) - 1}"
    st.session_state.message_metrics_snapshots[message_id] = current_metrics.copy()
    st.session_state.message_timestamps[message_id] = response_time


st.markdown("---")

# Check thresholds and auto-analyze if needed (happens before AI insights banner)
if st.session_state.use_real_metrics:
    current_metrics = st.session_state.prometheus_client.get_metrics()
    simulator_for_charts = st.session_state.prometheus_client
else:
    current_metrics = st.session_state.simulator.generate_metrics()
    simulator_for_charts = st.session_state.simulator

# Save metrics to database for historical analysis
st.session_state.metrics_db.save_metrics(
    cluster_name=st.session_state.selected_cluster,
    metrics=current_metrics
)

# Cleanup old data (keep only 24h)
st.session_state.metrics_db.cleanup_old_data()

# Check thresholds and auto-analyze if needed
severity, issues = check_thresholds(current_metrics)
current_time = time.time()

# Auto-analyze: On first load or when thresholds breach (every 60 seconds max)
if (st.session_state.latest_insight is None) or \
   (severity in ['CRITICAL', 'WARNING'] and current_time - st.session_state.last_auto_analysis > 60):
    with st.spinner("AI analyzing metrics..."):
        # If multiple models discovered, pass comparison context
        models_context = None
        if st.session_state.discovered_models and len(st.session_state.discovered_models) > 1:
            # Build comparison context
            models_summary = []
            for service in st.session_state.discovered_models[:5]:  # Top 5 models
                try:
                    m = st.session_state.prometheus_client.get_metrics(
                        namespace=service['namespace'],
                        service=service['name']
                    )
                    models_summary.append({
                        'name': f"{service['namespace']}/{service.get('model', 'unknown')}",
                        'gpu': m.get('kv_cache_usage_perc', m.get('gpu_utilization', 0)),
                        'latency': m.get('e2e_request_latency_p90', 0),
                        'throughput': m.get('tokens_per_second', 0),
                        'queue': m.get('num_requests_waiting', 0)
                    })
                except:
                    continue

            if models_summary:
                models_context = f"\n\nMODEL COMPARISON ({len(models_summary)} models detected):\n"
                for m in models_summary:
                    models_context += f"- {m['name']}: GPU {m['gpu']}%, Latency {m['latency']}s, Throughput {m['throughput']} tok/s, Queue {m['queue']}\n"
                models_context += "\nIdentify outliers and compare performance across models."

        response = query_ollama(current_metrics, "", auto=True, models_context=models_context)
        st.session_state.latest_insight = response
        st.session_state.last_auto_analysis = current_time

        # Save insight to database
        severity_class, severity_text = get_severity_class(response)
        st.session_state.metrics_db.save_ai_insight(
            cluster_name=st.session_state.selected_cluster,
            severity=severity_text,
            insight_text=response,
            metrics_snapshot=current_metrics
        )

# Display Latest AI Insight Banner with actionable commands
if st.session_state.latest_insight:
    severity_class, severity_text = get_severity_class(st.session_state.latest_insight)

    # Reset CRITICAL approval if severity is no longer CRITICAL
    if severity_text != 'CRITICAL' and st.session_state.critical_actions_approved:
        st.session_state.critical_actions_approved = False
        st.session_state.critical_approval_timestamp = 0
    # Remove severity prefix from display text
    display_text = st.session_state.latest_insight
    for prefix in ['CRITICAL: ', 'WARNING: ', 'INFO: ']:
        if display_text.startswith(prefix):
            display_text = display_text[len(prefix):]
            break

    st.markdown(f"""
    <div class="alert-banner {severity_class}">
        <strong>Latest AI Insight</strong><br/>
        {display_text}
    </div>
    """, unsafe_allow_html=True)

    # Parse AI insight to generate actionable commands dynamically with cluster validation
    if severity in ['CRITICAL', 'WARNING'] and st.session_state.latest_insight:
        insight_text = st.session_state.latest_insight.lower()

        # Query cluster for current deployment state
        cluster_info = None
        deployment_found = False
        warnings = []

        if st.session_state.cluster_client.is_logged_in():
            # Try to find deployment in the expected namespace
            cluster_info = st.session_state.cluster_client.get_deployment_info(
                namespace="lightspeed-poc",
                deployment_name="vllm-llama-model-predictor"
            )
            deployment_found = cluster_info and cluster_info.get('exists', False)
        else:
            warnings.append("⚠️ Not logged into OpenShift cluster - commands may not work. Run: oc login <cluster-url>")

        # Parse AI recommendations and generate corresponding commands
        import re
        commands = []

        # Check for scaling recommendations
        if 'scale' in insight_text or 'replica' in insight_text:
            # Look for pattern like "1→2" or "from 1 to 2" or "from 1 to 2"
            scale_match = re.search(r'(?:from\s+)?(\d+)\s*(?:→|to)\s*(\d+)\s*replica', insight_text)

            # Rate-limiting check: Prevent thrashing from repeated scaling
            time_since_last_scaling = time.time() - st.session_state.last_scaling_action
            cooldown_seconds = st.session_state.scaling_cooldown_minutes * 60
            in_cooldown = time_since_last_scaling < cooldown_seconds

            if in_cooldown and scale_match:
                # Skip scaling command, show cooldown message
                minutes_remaining = int((cooldown_seconds - time_since_last_scaling) / 60)
                warnings.append(
                    f"⏳ Scaling cooldown active: {minutes_remaining} minute(s) remaining. "
                    f"This prevents rapid scaling thrashing. Last scaled {int(time_since_last_scaling/60)} minutes ago."
                )
            elif scale_match and deployment_found:
                current_replicas = cluster_info.get('replicas', 'unknown')
                new_replicas_str = scale_match.group(2)

                # Schema validation: Ensure replica count is valid
                try:
                    new_replicas = int(new_replicas_str)

                    # Sanity checks on replica count
                    if new_replicas < 1:
                        warnings.append(f"⚠️ Invalid replica count: {new_replicas}. Must be at least 1. Skipping command.")
                        new_replicas = None
                    elif new_replicas > 10:
                        warnings.append(f"⚠️ Replica count {new_replicas} seems too high (max 10). Please verify manually.")
                        new_replicas = None
                    elif current_replicas != 'unknown' and new_replicas == current_replicas:
                        warnings.append(f"⚠️ Target replicas ({new_replicas}) same as current. No action needed.")
                        new_replicas = None

                except (ValueError, TypeError):
                    warnings.append(f"⚠️ Invalid replica count '{new_replicas_str}'. Must be a number. Skipping command.")
                    new_replicas = None

                if new_replicas is not None:
                    deployment_name = cluster_info.get('name', 'vllm-llama-model-predictor')
                    namespace = cluster_info.get('namespace', 'lightspeed-poc')

                    cmd = f"oc scale deployment {deployment_name} --replicas={new_replicas} -n {namespace}"

                    # Extract expected impact from AI insight
                    impact_match = re.search(r'expected[:\s]+([^.]+)', insight_text, re.IGNORECASE)
                    impact = impact_match.group(1) if impact_match else "Improve cluster performance"

                    commands.append({
                        'command': cmd,
                        'impact': impact.capitalize(),
                        'validation': f"Current replicas: {current_replicas} → Target: {new_replicas}",
                        'safe': True
                    })

                    # Update last scaling action timestamp
                    st.session_state.last_scaling_action = time.time()

            elif scale_match and not deployment_found and not in_cooldown:
                # Generate command but mark as unvalidated
                new_replicas = scale_match.group(2)
                cmd = f"oc scale deployment vllm-llama-model-predictor --replicas={new_replicas} -n lightspeed-poc"

                commands.append({
                    'command': cmd,
                    'impact': "Improve cluster performance (unvalidated)",
                    'validation': "⚠️ Could not verify deployment exists",
                    'safe': False
                })

                # Update last scaling action timestamp
                st.session_state.last_scaling_action = time.time()

        # Check for batch size recommendations
        if 'batch' in insight_text:
            batch_match = re.search(r'(?:batch.*?size.*?|size.*?batch.*?)(\d+)', insight_text)
            if batch_match:
                batch_size_str = batch_match.group(1)

                # Schema validation: Ensure batch size is valid
                try:
                    batch_size = int(batch_size_str)

                    # Sanity checks on batch size
                    if batch_size < 1:
                        warnings.append(f"⚠️ Invalid batch size: {batch_size}. Must be at least 1. Skipping command.")
                        batch_size = None
                    elif batch_size > 256:
                        warnings.append(f"⚠️ Batch size {batch_size} seems too high (max 256). Please verify manually.")
                        batch_size = None

                except (ValueError, TypeError):
                    warnings.append(f"⚠️ Invalid batch size '{batch_size_str}'. Must be a number. Skipping command.")
                    batch_size = None

                if batch_size is not None and deployment_found:
                    deployment_name = cluster_info.get('name', 'vllm-llama-model-predictor')
                    namespace = cluster_info.get('namespace', 'lightspeed-poc')
                    current_batch = cluster_info.get('env_vars', {}).get('MAX_BATCH_SIZE', 'unknown')

                    cmd = f"oc set env deployment/{deployment_name} MAX_BATCH_SIZE={batch_size} -n {namespace}"

                    commands.append({
                        'command': cmd,
                        'impact': "Improve GPU utilization",
                        'validation': f"Current batch size: {current_batch} → Target: {batch_size}",
                        'safe': True
                    })
                elif batch_size is not None and not deployment_found:
                    cmd = f"oc set env deployment/vllm-llama-model-predictor MAX_BATCH_SIZE={batch_size} -n lightspeed-poc"
                    commands.append({
                        'command': cmd,
                        'impact': "Improve GPU utilization (unvalidated)",
                        'validation': "⚠️ Could not verify deployment exists",
                        'safe': False
                    })

        # Check for GPU/memory recommendations
        if 'memory' in insight_text or 'gpu' in insight_text:
            if 'increase' in insight_text or 'more' in insight_text:
                if deployment_found:
                    deployment_name = cluster_info.get('name', 'vllm-llama-model-predictor')
                    namespace = cluster_info.get('namespace', 'lightspeed-poc')
                    current_resources = cluster_info.get('resources', {})

                    cmd = f"oc set resources deployment/{deployment_name} --limits=memory=16Gi,nvidia.com/gpu=2 -n {namespace}"

                    commands.append({
                        'command': cmd,
                        'impact': "Increase available resources",
                        'validation': f"Current: {current_resources.get('memory', 'unknown')} memory, {current_resources.get('gpu', 'unknown')} GPUs",
                        'safe': True
                    })
                else:
                    cmd = "oc set resources deployment/vllm-llama-model-predictor --limits=memory=16Gi,nvidia.com/gpu=2 -n lightspeed-poc"
                    commands.append({
                        'command': cmd,
                        'impact': "Increase available resources (unvalidated)",
                        'validation': "⚠️ Could not verify current resource allocation",
                        'safe': False
                    })

        # Display warnings if any
        if warnings:
            for warning in warnings:
                st.warning(warning)

        # Display commands prominently - NO EXPANDER, always visible
        if commands:
            st.markdown("### ⚡ Recommended Actions")

            # CRITICAL actions require human approval
            if severity_text == 'CRITICAL':
                if not st.session_state.critical_actions_approved:
                    # Show approval UI
                    st.warning("🚨 CRITICAL actions require manual review and approval")

                    st.markdown("""
                    **Before executing these commands, please review:**
                    - Current system state and metrics
                    - Expected impact of the recommended actions
                    - Rollback plan if something goes wrong
                    """)

                    col1, col2 = st.columns([1, 3])
                    with col1:
                        if st.button("✓ Review & Approve", type="primary", use_container_width=True):
                            st.session_state.critical_actions_approved = True
                            st.session_state.critical_approval_timestamp = time.time()

                            # Log approval to database
                            st.session_state.metrics_db.save_ai_insight(
                                cluster_name=st.session_state.selected_cluster,
                                severity="APPROVAL",
                                insight_text=f"User approved CRITICAL action at {time.strftime('%Y-%m-%d %H:%M:%S')}",
                                metrics_snapshot=current_metrics
                            )
                            st.rerun()

                    with col2:
                        understand_risks = st.checkbox("I understand the risks and have a rollback plan")
                        if not understand_risks:
                            st.caption("⚠️ Please confirm you understand the risks before approving")

                    # Don't show commands until approved
                    st.info("Commands will appear here after approval")
                    st.stop()  # Stop rendering here until approved

                else:
                    # Approved - show approval status
                    approval_time = time.strftime('%H:%M:%S', time.localtime(st.session_state.critical_approval_timestamp))
                    st.success(f"✓ CRITICAL actions approved at {approval_time}")

            st.caption("AI-generated and cluster-validated commands ready to execute:")

            for i, cmd_info in enumerate(commands, 1):
                # Create a prominent card for each command
                if cmd_info['safe']:
                    st.markdown(f"""
                    <div style="background-color: #d4edda; border-left: 4px solid #28a745; padding: 1rem; border-radius: 0.5rem; margin: 1rem 0;">
                        <strong style="color: #155724;">✓ Validated Command {i}</strong>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 1rem; border-radius: 0.5rem; margin: 1rem 0;">
                        <strong style="color: #856404;">⚠️ Unvalidated Command {i}</strong>
                    </div>
                    """, unsafe_allow_html=True)

                # Command with copy button
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.code(cmd_info['command'], language="bash")
                with col2:
                    st.button("📋 Copy", key=f"copy_cmd_{i}", help="Click to copy command")

                # Impact and validation info
                st.markdown(f"**💡 Expected Impact:** {cmd_info['impact']}")
                st.markdown(f"**🔍 Validation:** {cmd_info['validation']}")

                if i < len(commands):
                    st.markdown("<br>", unsafe_allow_html=True)

# Quick actions (moved to below chat)
col_clear1, col_clear2 = st.columns(2)
with col_clear1:
    if st.button("Clear Chat", key="clear_chat_btn", use_container_width=True):
        st.session_state.messages = []
        st.session_state.message_metrics_snapshots = {}
        st.session_state.message_timestamps = {}
        st.rerun()
with col_clear2:
    if st.button("View History", key="view_history_btn", use_container_width=True):
        st.session_state.show_history = True
        st.rerun()


# Historical Metrics Viewer
if st.session_state.get('show_history', False):
    st.markdown("---")
    st.markdown("### Historical Metrics Viewer")

    col_close, col_time = st.columns([10, 2])
    with col_close:
        st.caption("View detailed metrics history from the database")
    with col_time:
        if st.button("Close", key="close_history"):
            st.session_state.show_history = False
            st.rerun()

    # Time range selector
    time_range = st.selectbox(
        "Select time range",
        ["Last 1 hour", "Last 6 hours", "Last 12 hours", "Last 24 hours"],
        index=3
    )

    hours_map = {
        "Last 1 hour": 1,
        "Last 6 hours": 6,
        "Last 12 hours": 12,
        "Last 24 hours": 24
    }
    selected_hours = hours_map[time_range]

    # Get historical data
    historical_data = st.session_state.metrics_db.get_recent_metrics(
        hours=selected_hours,
        cluster_name=st.session_state.selected_cluster
    )

    if not historical_data.empty:
        # Show summary stats
        summary = st.session_state.metrics_db.get_summary_stats(
            hours=selected_hours,
            cluster_name=st.session_state.selected_cluster
        )

        if summary:
            st.markdown(f"#### Summary Statistics ({time_range})")
            summary_cols = st.columns(6)

            with summary_cols[0]:
                st.metric("Data Points", summary['data_points'])
            with summary_cols[1]:
                st.metric("Avg KV Cache", f"{summary['avg_kv_cache']:.1f}%")
            with summary_cols[2]:
                st.metric("Max KV Cache", f"{summary['max_kv_cache']:.1f}%")
            with summary_cols[3]:
                st.metric("Avg Latency", f"{summary['avg_latency']:.2f}s")
            with summary_cols[4]:
                st.metric("Max Latency", f"{summary['max_latency']:.2f}s")
            with summary_cols[5]:
                st.metric("Tokens Generated", f"{int(summary['total_tokens_generated']):,}")

        # Show AI insights history
        st.markdown("#### AI Insights History")
        insights_data = st.session_state.metrics_db.get_recent_insights(
            hours=selected_hours,
            cluster_name=st.session_state.selected_cluster,
            limit=50
        )

        if not insights_data.empty:
            # Rename columns for better display
            display_insights = insights_data[['timestamp', 'severity', 'insight_text']].copy()
            display_insights.columns = ['Time', 'Severity', 'AI Recommendation']
            st.dataframe(
                display_insights,
                use_container_width=True,
                height=300
            )
        else:
            st.info("No AI insights recorded during this time period")

        # Show raw data table
        with st.expander("View Raw Historical Data"):
            st.dataframe(
                historical_data[['timestamp', 'kv_cache_usage', 'num_requests_running',
                                'num_requests_waiting', 'failure_rate', 'latency_p90',
                                'tokens_per_second']].sort_values('timestamp', ascending=False),
                use_container_width=True,
                height=400
            )

            # Export button
            if st.button("Export Historical Data to CSV"):
                filename = st.session_state.metrics_db.export_to_csv(
                    hours=selected_hours,
                    cluster_name=st.session_state.selected_cluster
                )
                if filename:
                    st.success(f"Exported to {filename}")
                else:
                    st.warning("No data to export")
    else:
        st.info(f"No historical data available for the selected time range ({time_range})")

# Only show live metrics and trend analysis if not viewing history
if not st.session_state.get('show_history', False):
    st.markdown("---")

    # Main content layout - Full width for metrics
    st.markdown("### Live Metrics")

    # Cluster info banner
    gpu_type = current_metrics.get('gpu_type', 'Unknown')
    gpu_arch = current_metrics.get('gpu_architecture', 'Unknown')
    cuda_version = current_metrics.get('cuda_version', 'Unknown')
    model_name = current_metrics.get('model_name', 'Unknown')
    namespace = current_metrics.get('namespace', 'Unknown')
    batch_size = current_metrics.get('batch_size')
    max_num_seqs = current_metrics.get('max_num_seqs')
    replica_count = current_metrics.get('replica_count', 1)
    cluster_name = st.session_state.selected_cluster

    # Build third line - only show batch config if explicitly set
    config_line = f"<strong>Model:</strong> {model_name} | <strong>GPU:</strong> {gpu_type} ({gpu_arch}) | <strong>CUDA:</strong> {cuda_version}"

    if batch_size or max_num_seqs:
        config_line += "<br>"
        config_parts = []
        if batch_size:
            config_parts.append(f"<strong>Batch Size:</strong> {batch_size} tokens")
        if max_num_seqs:
            config_parts.append(f"<strong>Max Sequences:</strong> {max_num_seqs}")
        config_line += " | ".join(config_parts)

    st.markdown(f"""
    <div style="background: #f0f2f6; padding: 0.75rem 1rem; border-radius: 0.5rem; margin-bottom: 1rem;">
        <strong>Cluster:</strong> {cluster_name} | <strong>Namespace:</strong> {namespace} | <strong>Replicas:</strong> {replica_count}<br>
        {config_line}
    </div>
    """, unsafe_allow_html=True)

    # Display key metrics in cards with colored backgrounds
    metric_cols = st.columns(6)

    with metric_cols[0]:
        kv_cache = current_metrics.get('kv_cache_usage_perc', current_metrics.get('gpu_utilization', 0))
        if kv_cache > 85:
            card_class = "metric-card-critical"
            status = "Critical"
        elif kv_cache > 70:
            card_class = "metric-card-warning"
            status = "Warning"
        else:
            card_class = "metric-card-healthy"
            status = "Healthy"

        st.markdown(f'<div class="{card_class}" style="padding: 1rem; border-radius: 0.5rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.metric("KV Cache", f"{kv_cache}%", delta=None, help="vLLM KV cache block utilization (memory pressure indicator). High % = running out of GPU memory blocks.")
        st.caption(f"{status}")
        st.markdown('</div>', unsafe_allow_html=True)

    with metric_cols[1]:
        gpu_compute = current_metrics.get('gpu_compute_utilization', 0)
        if gpu_compute > 90:
            card_class = "metric-card-warning"  # High compute is not critical, just busy
            status = "Very Busy"
        elif gpu_compute > 70:
            card_class = "metric-card-healthy"  # High compute is good
            status = "Busy"
        else:
            card_class = "metric-card-healthy"
            status = "Idle"

        st.markdown(f'<div class="{card_class}" style="padding: 1rem; border-radius: 0.5rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.metric("GPU Compute", f"{gpu_compute}%", delta=None, help="GPU compute utilization (how busy the GPU cores are). High % = GPU is actively processing.")
        st.caption(f"{status}")
        st.markdown('</div>', unsafe_allow_html=True)

    with metric_cols[2]:
        ttft = current_metrics['time_to_first_token_p90']
        if ttft > 2:
            card_class = "metric-card-critical"
            status = "Critical"
        elif ttft > 1:
            card_class = "metric-card-warning"
            status = "Warning"
        else:
            card_class = "metric-card-healthy"
            status = "Healthy"

        st.markdown(f'<div class="{card_class}" style="padding: 1rem; border-radius: 0.5rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.metric("TTFT P90", f"{ttft}s", delta=None, help="Time To First Token: How long until the model starts generating. Low (<1s) = fast prefill. High (>2s) = slow prefill or queuing.")
        st.caption(status)
        st.markdown('</div>', unsafe_allow_html=True)

    with metric_cols[3]:
        latency = current_metrics['e2e_request_latency_p90']
        if latency > 5:
            card_class = "metric-card-critical"
            status = "Critical"
        elif latency > 3:
            card_class = "metric-card-warning"
            status = "Warning"
        else:
            card_class = "metric-card-healthy"
            status = "Healthy"

        st.markdown(f'<div class="{card_class}" style="padding: 1rem; border-radius: 0.5rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.metric("E2E Latency P90", f"{latency}s", delta=None, help="End-to-End Latency: Total time from request to completion (includes TTFT + generation time).")
        st.caption(status)
        st.markdown('</div>', unsafe_allow_html=True)

    with metric_cols[4]:
        waiting = current_metrics['num_requests_waiting']
        if waiting > 15:
            card_class = "metric-card-critical"
            status = "Critical"
        elif waiting > 5:
            card_class = "metric-card-warning"
            status = "Warning"
        else:
            card_class = "metric-card-healthy"
            status = "Healthy"

        st.markdown(f'<div class="{card_class}" style="padding: 1rem; border-radius: 0.5rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.metric("Waiting Requests", waiting, delta=None)
        st.caption(status)
        st.markdown('</div>', unsafe_allow_html=True)

    with metric_cols[5]:
        throughput = current_metrics['tokens_per_second']
        if throughput < 100:
            card_class = "metric-card-warning"
            status = "Low"
        elif throughput >= 400:
            card_class = "metric-card-healthy"
            status = "Excellent"
        else:
            card_class = "metric-card-healthy"
            status = "Good"

        st.markdown(f'<div class="{card_class}" style="padding: 1rem; border-radius: 0.5rem; margin-bottom: 0.5rem;">', unsafe_allow_html=True)
        st.metric("Throughput", f"{throughput} tok/s", delta=None, help="System-wide token generation rate. Higher is better.")
        st.caption(status)
        st.markdown('</div>', unsafe_allow_html=True)

    # Token distribution section
    st.markdown("#### Token Distribution")

    # Show P90 token values at the top
    prompt_p90 = current_metrics.get('prompt_tokens_p90', 0)
    gen_p90 = current_metrics.get('generation_tokens_p90', 0)
    if prompt_p90 > 0 or gen_p90 > 0:
        st.caption(f"Input/Output: {int(prompt_p90)} / {int(gen_p90)} tokens (P90)")
    else:
        st.caption("Understanding your workload's token usage patterns")

    token_cols = st.columns(2)

    with token_cols[0]:
        st.markdown("**Input Tokens (Prompts)**")
        input_col1, input_col2, input_col3 = st.columns(3)
        with input_col1:
            st.metric("P50", f"{current_metrics.get('prompt_tokens_p50', 0)}")
        with input_col2:
            st.metric("P90", f"{current_metrics.get('prompt_tokens_p90', 0)}")
        with input_col3:
            st.metric("P99", f"{current_metrics.get('prompt_tokens_p99', 0)}")

    with token_cols[1]:
        st.markdown("**Output Tokens (Generated)**")
        output_col1, output_col2, output_col3 = st.columns(3)
        with output_col1:
            st.metric("P50", f"{current_metrics.get('generation_tokens_p50', 0)}")
        with output_col2:
            st.metric("P90", f"{current_metrics.get('generation_tokens_p90', 0)}")
        with output_col3:
            st.metric("P99", f"{current_metrics.get('generation_tokens_p99', 0)}")

    st.markdown("---")

    # Time series charts
    st.markdown("#### Trend Analysis (Last 15 minutes)")
    st.caption("Red dashed lines = critical thresholds | Orange dashed lines = warning thresholds")
    chart = create_metrics_chart(simulator_for_charts)
    if chart:
        st.plotly_chart(chart, use_container_width=True)
    else:
        st.info("Collecting metrics... Charts will appear after a few updates.")

    st.markdown("---")

    # Response Time Distribution (Perses-style)
    st.markdown("#### Response Time Distribution")
    st.caption("Request latency breakdown across performance categories")

    # Get historical latency data from simulator
    if hasattr(simulator_for_charts, 'history') and 'e2e_request_latency_p90' in simulator_for_charts.history:
        latency_data = simulator_for_charts.history['e2e_request_latency_p90']

        # Categorize into buckets
        fast = sum(1 for x in latency_data if x < 1.0)
        acceptable = sum(1 for x in latency_data if 1.0 <= x < 3.0)
        slow = sum(1 for x in latency_data if 3.0 <= x < 5.0)
        degraded = sum(1 for x in latency_data if x >= 5.0)
        total = len(latency_data)

        if total > 0:
            # Create horizontal bar chart
            fig_dist = go.Figure()

            categories = ['Fast (<1s)', 'Acceptable (1-3s)', 'Slow (3-5s)', 'Degraded (≥5s)']
            values = [fast, acceptable, slow, degraded]
            percentages = [(v/total)*100 for v in values]
            colors = ['#28a745', '#17a2b8', '#ffc107', '#dc3545']

            fig_dist.add_trace(go.Bar(
                y=categories,
                x=percentages,
                orientation='h',
                marker=dict(color=colors),
                text=[f"{p:.1f}% ({v}/{total})" for p, v in zip(percentages, values)],
                textposition='auto',
                hovertemplate='<b>%{y}</b><br>%{x:.1f}%<extra></extra>'
            ))

            fig_dist.update_layout(
                xaxis_title="Percentage of Requests",
                yaxis_title="",
                height=250,
                showlegend=False,
                template='plotly_white',
                margin=dict(l=20, r=20, t=20, b=40)
            )
            fig_dist.update_xaxes(range=[0, 100], showgrid=True, gridwidth=1, gridcolor='LightGray')

            st.plotly_chart(fig_dist, use_container_width=True)

            # Summary metrics
            col1, col2, col3 = st.columns(3)
            with col1:
                healthy_pct = ((fast + acceptable) / total) * 100
                st.metric("Healthy Requests", f"{healthy_pct:.1f}%", help="Fast + Acceptable (<3s)")
            with col2:
                current_latency = current_metrics.get('e2e_request_latency_p90', 0)
                if current_latency < 1:
                    category = "Fast"
                elif current_latency < 3:
                    category = "Acceptable"
                elif current_latency < 5:
                    category = "Slow"
                else:
                    category = "Degraded"
                st.metric("Current P90", f"{current_latency:.2f}s ({category})")
            with col3:
                avg_latency = sum(latency_data) / total if total > 0 else 0
                st.metric("Average Latency", f"{avg_latency:.2f}s")
        else:
            st.info("Collecting latency data... Distribution will appear after a few updates.")
    else:
        st.info("Collecting latency data... Distribution will appear after a few updates.")

    st.markdown("---")

    # Current metrics table
    with st.expander("View Raw Metrics"):
        st.json(current_metrics)

# Auto-refresh every 20 seconds (only if not paused)
if not st.session_state.auto_refresh_paused:
    time.sleep(20)
    st.rerun()
else:
    # Show message that auto-refresh is paused
    st.info("⏸ Auto-refresh paused. Click 'Resume Auto-Refresh' in the sidebar to continue updates.")
