"""
Pre-classification layer for vLLM bottleneck detection
Reduces cognitive load on 8B models by filtering decision space
"""

def classify_bottleneck_type(metrics):
    """
    Rule-based pre-classification to narrow LLM's decision space.

    Returns:
        str: One of ["decode_bound", "queuing", "prefill_bound", "compute_bound", "healthy", "unclear"]
    """
    # Extract key signals
    waiting = metrics.get('num_requests_waiting', 0)
    running = metrics.get('num_requests_running', 1)  # avoid div/0
    gpu_util = metrics.get('gpu_compute_utilization', 0)
    ttft_p90 = metrics.get('time_to_first_token_p90', 0)
    latency_p90 = metrics.get('e2e_request_latency_p90', 0)
    gen_tokens_p90 = metrics.get('generation_tokens_p90', 0)
    kv_cache = metrics.get('kv_cache_usage_perc', 0)
    throughput = metrics.get('tokens_per_second', 1)

    # Calculate derived signals
    decode_time_estimate = latency_p90 - ttft_p90
    expected_decode_time = gen_tokens_p90 * 0.02  # ~20ms per token baseline for A10G

    # Deterministic pre-classification

    # 1. QUEUING: Actual queue backlog exists
    if waiting > 5 and waiting > running * 0.3:
        return "queuing"

    # 2. PREFILL_BOUND: Slow prefill with high GPU usage
    if ttft_p90 > 2.0 and gpu_util > 70:
        return "prefill_bound"

    # 3. DECODE_BOUND: Long generations with low GPU (expected behavior)
    # Calculate per-request decode speed properly
    decode_time = decode_time_estimate
    # Total throughput divided by concurrent requests = per-request speed
    tokens_per_second_per_request = throughput / running if running > 0 else 0

    if (gen_tokens_p90 > 200 and
        ttft_p90 < 0.5 and
        gpu_util < 30 and
        waiting == 0):
        # For A10G with long outputs (400+ tokens), expect 15-25 tok/s per request
        # This is NORMAL decode-bound behavior, not a problem
        expected_min_speed = 15
        expected_max_speed = 30

        if expected_min_speed <= tokens_per_second_per_request <= expected_max_speed:
            # Performance is normal for decode-bound workload
            return "decode_bound_healthy"
        elif tokens_per_second_per_request < expected_min_speed:
            # Slower than expected - could be batching issue
            return "gpu_underutilization"
        else:
            # Faster than expected - performing well
            return "decode_bound_healthy"

    # 4. COMPUTE_BOUND: High GPU usage with good performance
    if gpu_util > 85 and ttft_p90 < 1.0 and latency_p90 < 5.0:
        return "compute_bound"

    # 5. MEMORY_PRESSURE: High KV cache usage
    if kv_cache > 85:
        return "memory_pressure"

    # 6. HEALTHY: Good metrics, low latency, no queue
    if (latency_p90 < 3.0 and
        waiting == 0 and
        kv_cache < 70 and
        throughput > 200):
        return "healthy"

    # 7. UNCLEAR: Needs LLM analysis
    return "unclear"


def get_severity_from_category(category, metrics):
    """Map bottleneck category to severity level"""

    kv_cache = metrics.get('kv_cache_usage_perc', 0)
    waiting = metrics.get('num_requests_waiting', 0)
    failure_rate = metrics.get('request_failure_rate', 0)

    # CRITICAL overrides
    if kv_cache > 85 or waiting > 15 or failure_rate > 5:
        return "CRITICAL"

    # Category-based severity
    severity_map = {
        "queuing": "WARNING",
        "prefill_bound": "WARNING",
        "gpu_underutilization": "WARNING",  # Severe waste of resources
        "memory_pressure": "CRITICAL",
        "compute_bound": "INFO",  # High GPU is good if performing well
        "decode_bound": "INFO",   # Expected behavior (legacy)
        "decode_bound_healthy": "INFO",  # Normal decode-bound operation
        "healthy": "INFO",
        "unclear": "INFO"
    }

    return severity_map.get(category, "INFO")


def get_diagnostic_summary(category, metrics):
    """Generate human-readable summary for each category"""

    waiting = metrics.get('num_requests_waiting', 0)
    running = metrics.get('num_requests_running', 0)
    gpu_util = metrics.get('gpu_compute_utilization', 0)
    ttft_p90 = metrics.get('time_to_first_token_p90', 0)
    latency_p90 = metrics.get('e2e_request_latency_p90', 0)
    gen_tokens_p90 = metrics.get('generation_tokens_p90', 0)
    throughput = metrics.get('tokens_per_second', 0)
    kv_cache = metrics.get('kv_cache_usage_perc', 0)

    # Calculate decode speed for gpu_underutilization summary
    decode_time = latency_p90 - ttft_p90
    tok_per_sec_per_req = gen_tokens_p90 / decode_time if decode_time > 0 else 0

    # KV cache headroom
    kv_headroom = 100 - kv_cache

    summaries = {
        "queuing": f"Queue backlog detected: {waiting} requests waiting with {running} running. Latency: {latency_p90:.1f}s.",
        "prefill_bound": f"Slow prefill phase: TTFT {ttft_p90:.1f}s with {gpu_util}% GPU usage.",
        "gpu_underutilization": f"Severe GPU underutilization: {gpu_util}% compute, {kv_cache}% KV cache despite {running} concurrent requests. Root cause: Inefficient decode batching. Prefill is healthy (TTFT={ttft_p90:.1f}s), but decode is bottlenecked at {tok_per_sec_per_req:.0f} tok/s per request (should be 80-120 tok/s). Total latency P90: {latency_p90:.1f}s for {gen_tokens_p90} tokens (expected: 3-4s). KV cache headroom: {kv_headroom}% unused - can support 3-4x more load.",
        "decode_bound": f"Decode-bound workload: {gen_tokens_p90} tokens avg, latency {latency_p90:.1f}s is expected for token-by-token generation. GPU underutilized ({gpu_util}%) but performing at expected speed.",
        "decode_bound_healthy": f"System operating normally with capacity headroom. Current: {running} concurrent requests, {waiting} waiting, {gpu_util}% GPU, {kv_cache}% KV cache. Performance: P90 latency {latency_p90:.1f}s for {gen_tokens_p90}-token outputs ({tok_per_sec_per_req:.1f} tok/s per request). TTFT P90: {ttft_p90:.1f}s (excellent - prefill is healthy). A10G baseline for {gen_tokens_p90}-token decode: 15-25 tok/s per request ✓. No request queue (waiting={waiting}) = No batching opportunity ✓. {kv_headroom}% KV headroom = Can handle 3-4x traffic spikes ✓. Low GPU ({gpu_util}%) = Decode-bound workload with spare capacity ✓.",
        "compute_bound": f"GPU working hard: {gpu_util}% utilization with {throughput:.0f} tok/s throughput - system performing well.",
        "memory_pressure": f"Memory pressure: KV cache at {kv_cache}% - risk of OOM.",
        "healthy": f"System healthy: {latency_p90:.1f}s latency, {throughput:.0f} tok/s, no queue.",
        "unclear": f"Mixed signals: Latency {latency_p90:.1f}s, GPU {gpu_util}%, {waiting} waiting."
    }

    return summaries.get(category, "Unknown bottleneck type")


def get_recommendation(category, metrics):
    """Get specific recommendation for each bottleneck type"""

    recommendations = {
        "queuing": {
            "action": "Increase max_num_seqs to allow more concurrent requests",
            "steps": [
                "Edit deployment: oc edit deployment <name> -n <namespace>",
                "Add env var: MAX_NUM_SEQS=384 (increase from current)",
                "Verify: oc rollout status deployment/<name> -w"
            ],
            "expected_improvement": "Requests waiting: decreases to 0-2 | Latency: improves as queue drains"
        },
        "prefill_bound": {
            "action": "Increase max_num_batched_tokens for better prefill batching",
            "steps": [
                "Edit deployment: oc edit deployment <name> -n <namespace>",
                "Add env var: MAX_NUM_BATCHED_TOKENS=4096 (increase from 2048)",
                "Verify: oc rollout status deployment/<name> -w"
            ],
            "expected_improvement": "TTFT P90: decreases from current to <1.0s | Throughput: increases 20-40%"
        },
        "gpu_underutilization": {
            "action": "Increase batching parameters to improve GPU utilization",
            "steps": [
                "Prerequisite: Check current settings with 'oc get deployment <name> -n <namespace> -o yaml | grep -A5 env'",
                "Edit deployment: oc edit deployment <name> -n <namespace>",
                "Update environment variables:",
                "  - MAX_NUM_SEQS=256 (increase from current, likely 32-64)",
                "  - MAX_NUM_BATCHED_TOKENS=32768 (allows ~128 concurrent 256-token sequences)",
                "  - Optional: ENABLE_PREFIX_CACHING=true (if requests share prefixes)",
                "  - Optional: ENABLE_CHUNKED_PREFILL=true (improves continuous batching)",
                "Monitor rollout: oc rollout status deployment/<name> -w"
            ],
            "expected_improvement": "GPU utilization: increases to 60-80% | Throughput: increases 2-3x | Latency P90: decreases to 3-5s | Decode speed: 80-120 tok/s per request | TTFT: remains <0.2s (no regression) | Monitor: No OOM errors in logs"
        },
        "decode_bound": {
            "action": "Optional - Enable speculative decoding for faster decode (1.5-2x speedup)",
            "steps": [
                "Consider adding speculative decoding (requires draft model)",
                "Or enable prefix caching to reduce redundant computation",
                "Current performance is expected for long-form generation"
            ],
            "expected_improvement": "Latency: may improve 30-50% with speculative decoding | GPU utilization: may increase to 15-25%"
        },
        "decode_bound_healthy": {
            "action": "No action needed - system is right-sized for current load",
            "steps": [
                "Continue monitoring metrics",
                "Scale up ONLY when: waiting > 0 for >2 min OR request rate increases >2x",
                "Current performance is normal for this workload"
            ],
            "expected_improvement": "Metrics remain stable at current levels. Action needed only if traffic patterns change significantly."
        },
        "compute_bound": {
            "action": "No action needed - system performing optimally",
            "steps": [
                "Monitor for sustained high GPU usage",
                "Consider horizontal scaling if latency increases"
            ],
            "expected_improvement": "Metrics remain stable"
        },
        "memory_pressure": {
            "action": "Scale to 2 replicas immediately or reduce max_num_seqs",
            "steps": [
                "Edit deployment: oc edit deployment <name> -n <namespace>",
                "Change: replicas 1 → 2",
                "Verify: oc get pods -n <namespace>"
            ],
            "expected_improvement": "KV cache: decreases from current to 40-50% | Prevents OOM crashes"
        },
        "healthy": {
            "action": "No action needed - system operating normally",
            "steps": [
                "Continue monitoring metrics",
                "No changes required"
            ],
            "expected_improvement": "Metrics remain stable"
        },
        "unclear": {
            "action": "Monitor and collect more data",
            "steps": [
                "Check if this is a transient state",
                "Monitor for 5-10 minutes",
                "Review vLLM logs for errors"
            ],
            "expected_improvement": "Pattern should become clearer with more data"
        }
    }

    return recommendations.get(category, recommendations["unclear"])
