"""
Simplified prompts for Granite 3 Dense 8B with pre-classification
Uses hybrid approach: Python rules + targeted LLM formatting
"""

import json
from bottleneck_classifier import (
    classify_bottleneck_type,
    get_severity_from_category,
    get_diagnostic_summary,
    get_recommendation
)


def get_model_serving_auto_analysis_prompt(metrics, models_context=None):
    """
    Hybrid approach: Pre-classify bottleneck, then ask LLM to format output.

    Flow:
    1. Python rules determine bottleneck type
    2. Python rules provide recommendation
    3. LLM formats into user-friendly message with context
    """

    # Pre-classification (deterministic)
    bottleneck_category = classify_bottleneck_type(metrics)
    severity = get_severity_from_category(bottleneck_category, metrics)
    diagnostic_summary = get_diagnostic_summary(bottleneck_category, metrics)
    recommendation = get_recommendation(bottleneck_category, metrics)

    # Extract key metrics
    gpu_type = metrics.get('gpu_type', 'Unknown')
    kv_cache = metrics.get('kv_cache_usage_perc', 0)
    gpu_compute = metrics.get('gpu_compute_utilization', 0)
    latency = metrics.get('e2e_request_latency_p90', 0)
    throughput = metrics.get('tokens_per_second', 0)
    ttft = metrics.get('time_to_first_token_p90', 0)
    queue = metrics.get('num_requests_waiting', 0)
    running = metrics.get('num_requests_running', 0)
    gen_tokens = metrics.get('generation_tokens_p90', 0)

    # Simplified prompt - just format the pre-determined analysis
    return f"""You are a vLLM performance expert. Format this analysis into a clear, user-friendly message.

PRE-CLASSIFIED BOTTLENECK: {bottleneck_category}
SEVERITY: {severity}
DIAGNOSTIC SUMMARY: {diagnostic_summary}

CURRENT METRICS:
- GPU: {gpu_type}
- KV Cache: {kv_cache}% | GPU Compute: {gpu_compute}%
- Latency P90: {latency}s | TTFT P90: {ttft}s
- Generation Tokens P90: {gen_tokens}
- Throughput: {throughput} tok/s
- Queue: {queue} waiting | {running} running

RECOMMENDED ACTION:
{recommendation['action']}

IMPLEMENTATION STEPS:
{chr(10).join(f"{i+1}. {step}" for i, step in enumerate(recommendation['steps']))}

EXPECTED IMPROVEMENT:
{recommendation['expected_improvement']}

OUTPUT FORMAT (follow exactly):
[{severity}]: {diagnostic_summary}

Action: {recommendation['action']}
How to apply:
{chr(10).join(f"{i+1}. {step}" for i, step in enumerate(recommendation['steps']))}

✅ Success (within 3-5 min):
   {recommendation['expected_improvement']}

Your task: Output the above in the exact format shown, with proper formatting and clarity. Do NOT change the severity, diagnosis, or recommendations - just format them clearly."""


def get_model_serving_auto_analysis_prompt_direct(metrics, models_context=None):
    """
    Hybrid approach: Python for clear cases, AI for unclear/predictions.

    Flow:
    1. Pre-classify bottleneck type (Python rules)
    2. If CLEAR (queuing, gpu_underutilization, etc.) → return Python output
    3. If UNCLEAR or need predictions → use AI with targeted prompt
    """

    # Pre-classification (deterministic)
    bottleneck_category = classify_bottleneck_type(metrics)
    severity = get_severity_from_category(bottleneck_category, metrics)
    diagnostic_summary = get_diagnostic_summary(bottleneck_category, metrics)
    recommendation = get_recommendation(bottleneck_category, metrics)

    # If category is UNCLEAR, use AI for analysis
    if bottleneck_category == "unclear":
        # Return a prompt for AI to analyze
        return "USE_AI_ANALYSIS"  # Signal to use LLM

    # For clear cases, use Python output directly
    steps_formatted = "\n".join(f"{i+1}. {step}" for i, step in enumerate(recommendation['steps']))

    output = f"""[{severity}]: {diagnostic_summary}

Action: {recommendation['action']}
How to apply:
{steps_formatted}

✅ Success (within 3-5 min):
   {recommendation['expected_improvement']}"""

    return output


def get_model_serving_auto_analysis_prompt_ai(metrics, models_context=None):
    """
    AI-powered analysis for UNCLEAR cases and predictions.

    Use cases:
    1. Bottleneck category is "unclear" (mixed signals)
    2. Need to predict future trends
    3. Need to identify subtle patterns Python rules can't catch
    4. Need to correlate multiple metrics
    """

    # Pre-classification for context
    bottleneck_category = classify_bottleneck_type(metrics)

    # Extract key metrics
    gpu_type = metrics.get('gpu_type', 'Unknown')
    kv_cache = metrics.get('kv_cache_usage_perc', 0)
    gpu_compute = metrics.get('gpu_compute_utilization', 0)
    latency = metrics.get('e2e_request_latency_p90', 0)
    throughput = metrics.get('tokens_per_second', 0)
    ttft = metrics.get('time_to_first_token_p90', 0)
    queue = metrics.get('num_requests_waiting', 0)
    running = metrics.get('num_requests_running', 0)
    gen_tokens = metrics.get('generation_tokens_p90', 0)

    # Get historical context if available (for predictions)
    historical_note = ""
    if models_context:
        historical_note = f"\n\nHISTORICAL CONTEXT:\n{models_context}"

    return f"""You are a vLLM performance expert analyzing metrics that show mixed signals.

PRE-CLASSIFICATION: {bottleneck_category} (unclear pattern)

CURRENT METRICS:
- GPU: {gpu_type}
- KV Cache: {kv_cache}% | GPU Compute: {gpu_compute}%
- Latency P90: {latency}s | TTFT P90: {ttft}s
- Generation Tokens P90: {gen_tokens}
- Throughput: {throughput} tok/s
- Queue: {queue} waiting | {running} running

FULL METRICS:
{json.dumps(metrics, indent=2)}{historical_note}

YOUR TASK:
1. ANALYZE the metrics to identify subtle patterns or anomalies
2. PREDICT what might happen if current trend continues (next 10-30 min)
3. RECOMMEND specific actions with rationale
4. PROVIDE success indicators

OUTPUT FORMAT (follow exactly):
[SEVERITY]: [Your analysis in 2-3 sentences, including what makes this unclear]

Prediction (next 10-30 min if no action):
- [Metric 1]: likely to [increase/decrease/remain] because [reason]
- [Metric 2]: likely to [increase/decrease/remain] because [reason]

Action: [Specific recommendation]
How to apply:
1. [Step 1]
2. [Step 2]
3. [Step 3]

✅ Success (within 3-5 min):
   [Expected improvements using "increases from X to Y" or "decreases from X to Y"]

GUIDELINES:
- Focus on TRENDS and PREDICTIONS (this is where AI adds value vs rules)
- Identify correlations between metrics
- Consider workload patterns (burst traffic, gradual increase, etc.)
- If metrics are healthy but unusual, explain why it's interesting
- Use "increases from/decreases from/remains stable" for clarity"""


# For backward compatibility, keep the old function signature
def get_model_serving_chat_prompt(metrics, user_question):
    """Interactive chat still uses LLM for natural conversation"""

    gpu_type = metrics.get('gpu_type', 'Unknown')
    kv_cache = metrics.get('kv_cache_usage_perc', 0)
    gpu_compute = metrics.get('gpu_compute_utilization', 0)
    latency = metrics.get('e2e_request_latency_p90', 0)
    throughput = metrics.get('tokens_per_second', 0)
    bottleneck_category = classify_bottleneck_type(metrics)

    return f"""You are a vLLM performance expert answering questions about Red Hat OpenShift AI.

CURRENT STATE:
GPU: {gpu_type} | KV: {kv_cache}% | Compute: {gpu_compute}% | Throughput: {throughput} tok/s
Pre-classified workload: {bottleneck_category}

CURRENT METRICS:
{json.dumps(metrics, indent=2)}

USER QUESTION: {user_question}

Answer concisely (2-3 sentences) with specific vLLM recommendations."""


def get_cluster_dashboard_prompt(cluster_metrics, services_metrics):
    """Cluster-wide insights"""

    # For cluster view, still use LLM for synthesis
    return f"""You are analyzing a vLLM cluster with {cluster_metrics['total_models']} deployed models.

CLUSTER METRICS:
{json.dumps(cluster_metrics, indent=2)}

ANALYSIS FRAMEWORK:
1. Cluster Health: Are aggregate metrics within healthy ranges?
2. Resource Balance: Are some services overloaded while others idle?
3. Capacity: Are we approaching cluster limits?

OUTPUT FORMAT:
[SEVERITY]: [cluster diagnosis]. Recommendation: [cluster-wide action].

Analyze cluster state focusing on cross-service patterns:"""
