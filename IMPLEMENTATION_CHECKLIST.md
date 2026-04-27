# vLLM Metrics Implementation Checklist

## Quick Win Fixes (30 minutes)

### 1. Fix GPU Type Detection ✅
**File:** `vllm_metrics_scraper.py`, lines 98-143

**Current Problem:** Shows "Unknown GPU" even though vLLM exposes the device name

**Replace this section:**
```python
# Lines 98-143 - Current code tries cluster first, then memory inference
```

**With this:**
```python
def _get_gpu_type(self, raw_metrics):
    """Get GPU type with proper priority order"""

    # Priority 1: vLLM's direct device name metric (v0.5.0+)
    device_name = self.get_metric_value(raw_metrics, 'vllm:gpu_config_device_name')
    if device_name:
        return device_name

    # Priority 2: Check metric labels for gpu_type
    for metric_name in ['vllm:num_requests_running', 'vllm:gpu_cache_usage_perc']:
        if metric_name in raw_metrics:
            for metric in raw_metrics[metric_name]:
                if 'gpu_type' in metric.get('labels', {}):
                    return metric['labels']['gpu_type']

    # Priority 3: Cluster client (OpenShift node labels)
    if self.cluster_client and hasattr(self.cluster_client, 'get_gpu_type_from_nodes'):
        try:
            if self.cluster_client.is_logged_in():
                cluster_gpu = self.cluster_client.get_gpu_type_from_nodes()
                if cluster_gpu and cluster_gpu != "Unknown":
                    return cluster_gpu
        except:
            pass

    # Priority 4: Infer from GPU memory size (fallback)
    gpu_memory_bytes = self.get_metric_value(raw_metrics, 'vllm:gpu_config_total_memory_bytes')
    if gpu_memory_bytes:
        return self._infer_gpu_from_memory(gpu_memory_bytes)

    return "Unknown GPU"

def _infer_gpu_from_memory(self, gpu_memory_bytes):
    """Infer GPU type from memory size"""
    gpu_memory_gb = gpu_memory_bytes / (1024**3)

    # Common GPU memory sizes
    if 14 <= gpu_memory_gb < 20:
        return "NVIDIA T4 (16GB)"
    elif 22 <= gpu_memory_gb < 26:
        return "NVIDIA A10G (24GB)"
    elif 30 <= gpu_memory_gb < 34:
        return "NVIDIA V100 (32GB)"
    elif 38 <= gpu_memory_gb < 50:
        return "NVIDIA A100 (40GB)"
    elif 78 <= gpu_memory_gb < 90:
        return "NVIDIA A100 (80GB)"
    elif 46 <= gpu_memory_gb < 50:
        return "NVIDIA L40S (48GB)"
    elif 94 <= gpu_memory_gb < 100:
        return "NVIDIA H100 (80GB) HBM3"
    else:
        return f"GPU ({gpu_memory_gb:.0f}GB)"
```

**Then update line 96-144 to use this:**
```python
# In get_metrics() method, around line 96
metrics['gpu_type'] = self._get_gpu_type(raw_metrics)
```

**Expected Result:** GPU type should show "NVIDIA A10G" instead of "Unknown GPU"

---

### 2. Add Batching Metrics (Critical for Understanding Load)
**File:** `vllm_metrics_scraper.py`, after line 240

**Add these metrics extraction:**
```python
# Batching configuration (lines ~241-255)
max_seqs = self.get_metric_value(raw_metrics, 'vllm:max_num_seqs')
metrics['max_num_seqs'] = int(max_seqs) if max_seqs is not None else None

max_batched_tokens = self.get_metric_value(raw_metrics, 'vllm:max_num_batched_tokens')
metrics['max_num_batched_tokens'] = int(max_batched_tokens) if max_batched_tokens is not None else None

# Scheduler health
num_preemptions = self.get_metric_value(raw_metrics, 'vllm:num_preemptions_total')
metrics['num_preemptions_total'] = int(num_preemptions) if num_preemptions is not None else 0

# Calculate preemption rate (requires history)
if hasattr(self, 'last_preemptions') and hasattr(self, 'last_preemption_time'):
    time_diff = datetime.now().timestamp() - self.last_preemption_time
    if time_diff > 0:
        preemption_diff = metrics['num_preemptions_total'] - self.last_preemptions
        metrics['preemptions_per_minute'] = round((preemption_diff / time_diff) * 60, 1)
    else:
        metrics['preemptions_per_minute'] = 0.0
else:
    metrics['preemptions_per_minute'] = 0.0

# Store for next iteration
self.last_preemptions = metrics['num_preemptions_total']
self.last_preemption_time = datetime.now().timestamp()

# Calculate scheduler utilization
if metrics['max_num_seqs']:
    scheduler_util = (metrics['num_requests_running'] / metrics['max_num_seqs']) * 100
    metrics['scheduler_utilization_pct'] = round(scheduler_util, 1)
else:
    metrics['scheduler_utilization_pct'] = None
```

**Expected Result:** Dashboard will show:
- Max concurrent sequences allowed
- Scheduler utilization percentage
- Preemption rate (indicates thrashing)

---

### 3. Add KV Cache Block Metrics
**File:** `vllm_metrics_scraper.py`, after the batching metrics

**Add block-level visibility:**
```python
# KV Cache block metrics (lines ~270-290)
total_blocks = self.get_metric_value(raw_metrics, 'vllm:num_gpu_blocks_total')
free_blocks = self.get_metric_value(raw_metrics, 'vllm:num_gpu_blocks_free')

if total_blocks is not None:
    metrics['kv_cache_blocks_total'] = int(total_blocks)
    metrics['kv_cache_blocks_free'] = int(free_blocks) if free_blocks is not None else 0
    metrics['kv_cache_blocks_used'] = int(total_blocks - (free_blocks or 0))

    # More accurate block utilization
    if total_blocks > 0:
        block_util = (metrics['kv_cache_blocks_used'] / total_blocks) * 100
        metrics['kv_cache_block_utilization_pct'] = round(block_util, 1)
else:
    metrics['kv_cache_blocks_total'] = None
    metrics['kv_cache_blocks_free'] = None
    metrics['kv_cache_blocks_used'] = None
    metrics['kv_cache_block_utilization_pct'] = None

# CPU swap detection (CRITICAL)
cpu_cache = self.get_metric_value(raw_metrics, 'vllm:cpu_cache_usage_perc')
metrics['cpu_cache_usage_perc'] = int(cpu_cache * 100) if cpu_cache is not None else 0

num_swapped = self.get_metric_value(raw_metrics, 'vllm:num_requests_swapped')
metrics['num_requests_swapped'] = int(num_swapped) if num_swapped is not None else 0

# Set critical flag if swap is active
if metrics['num_requests_swapped'] > 0 or metrics['cpu_cache_usage_perc'] > 0:
    metrics['memory_swap_active'] = True
else:
    metrics['memory_swap_active'] = False
```

**Expected Result:**
- Absolute KV cache block counts (e.g., "2543/4096 blocks used")
- Detection of CPU swap (critical performance issue)

---

### 4. Add Accurate Throughput Metrics
**File:** `vllm_metrics_scraper.py`, lines 160-180

**Replace the current throughput calculation:**
```python
# Current code (lines 160-180) - DELETE THIS
gen_tokens_total = self.get_metric_value(raw_metrics, 'vllm:generation_tokens_total')
if gen_tokens_total is not None:
    current_time = datetime.now().timestamp()
    if hasattr(self, 'last_gen_tokens') and hasattr(self, 'last_timestamp'):
        time_diff = current_time - self.last_timestamp
        if time_diff > 0:
            token_diff = gen_tokens_total - self.last_gen_tokens
            metrics['tokens_per_second'] = int(token_diff / time_diff)
        else:
            metrics['tokens_per_second'] = 0
    else:
        metrics['tokens_per_second'] = 0
    self.last_gen_tokens = gen_tokens_total
    self.last_timestamp = current_time
else:
    metrics['tokens_per_second'] = 0
```

**Replace with this:**
```python
# Throughput - use vLLM's built-in average (more accurate)
avg_throughput = self.get_metric_value(raw_metrics, 'vllm:avg_generation_throughput_toks_per_s')

if avg_throughput is not None:
    # vLLM calculates this internally with proper windowing
    metrics['tokens_per_second'] = int(avg_throughput)
    metrics['avg_decode_speed_per_request'] = round(avg_throughput, 1)
else:
    # Fallback to manual calculation
    gen_tokens_total = self.get_metric_value(raw_metrics, 'vllm:generation_tokens_total')

    if gen_tokens_total is not None:
        current_time = datetime.now().timestamp()

        if hasattr(self, 'last_gen_tokens') and hasattr(self, 'last_timestamp'):
            time_diff = current_time - self.last_timestamp
            if time_diff > 0:
                token_diff = gen_tokens_total - self.last_gen_tokens
                metrics['tokens_per_second'] = int(token_diff / time_diff)
            else:
                metrics['tokens_per_second'] = 0
        else:
            metrics['tokens_per_second'] = 0

        self.last_gen_tokens = gen_tokens_total
        self.last_timestamp = current_time
    else:
        metrics['tokens_per_second'] = 0

    metrics['avg_decode_speed_per_request'] = None

# Prefill throughput
avg_prefill = self.get_metric_value(raw_metrics, 'vllm:avg_prompt_throughput_toks_per_s')
if avg_prefill is not None:
    metrics['avg_prefill_throughput'] = round(avg_prefill, 1)
else:
    metrics['avg_prefill_throughput'] = None
```

**Expected Result:**
- More accurate throughput numbers
- Separate prefill vs decode speeds
- Better diagnosis of slow TTFT

---

## Medium Priority (1-2 hours)

### 5. Add TPOT (Time Per Output Token) Metrics
**File:** `vllm_metrics_scraper.py`, after latency percentiles (~line 217)

```python
# TPOT (Time Per Output Token) - more accurate than calculation
tpot_p50 = self._estimate_percentile(raw_metrics, 'vllm:time_per_output_token_seconds', 0.5)
tpot_p90 = self._estimate_percentile(raw_metrics, 'vllm:time_per_output_token_seconds', 0.9)
tpot_p99 = self._estimate_percentile(raw_metrics, 'vllm:time_per_output_token_seconds', 0.99)

metrics['time_per_output_token_p50'] = round(tpot_p50 * 1000, 1) if tpot_p50 else None  # ms
metrics['time_per_output_token_p90'] = round(tpot_p90 * 1000, 1) if tpot_p90 else None
metrics['time_per_output_token_p99'] = round(tpot_p99 * 1000, 1) if tpot_p99 else None

# Inter-token latency (jitter detection)
itl_p50 = self._estimate_percentile(raw_metrics, 'vllm:inter_token_latency_seconds', 0.5)
itl_p90 = self._estimate_percentile(raw_metrics, 'vllm:inter_token_latency_seconds', 0.9)

if itl_p50 and itl_p90:
    metrics['inter_token_latency_p50'] = round(itl_p50 * 1000, 1)
    metrics['inter_token_latency_p90'] = round(itl_p90 * 1000, 1)

    # Detect high jitter
    if itl_p50 > 0 and (itl_p90 / itl_p50) > 2:
        metrics['token_latency_jitter'] = 'high'
    else:
        metrics['token_latency_jitter'] = 'normal'
else:
    metrics['inter_token_latency_p50'] = None
    metrics['inter_token_latency_p90'] = None
    metrics['token_latency_jitter'] = 'unknown'
```

**Expected Result:**
- Per-token decode time (more accurate than estimating from total)
- Jitter detection (scheduling inefficiency indicator)

---

### 6. Add Prefix Caching Metrics
**File:** `vllm_metrics_scraper.py`, after TPOT metrics

```python
# Prefix caching effectiveness (vLLM v0.6.2+)
cached_tokens = self.get_metric_value(raw_metrics, 'vllm:num_generation_tokens_from_cache_total')
total_gen_tokens = self.get_metric_value(raw_metrics, 'vllm:generation_tokens_total')

if cached_tokens is not None and total_gen_tokens is not None and total_gen_tokens > 0:
    cache_hit_rate = (cached_tokens / total_gen_tokens) * 100
    metrics['prefix_cache_hit_rate_pct'] = round(cache_hit_rate, 1)
    metrics['prefix_caching_enabled'] = True
else:
    metrics['prefix_cache_hit_rate_pct'] = 0
    metrics['prefix_caching_enabled'] = False
```

**Expected Result:**
- Shows if automatic prompt caching is working
- Cache hit rate percentage

---

### 7. Update Bottleneck Classifier with New Metrics
**File:** `bottleneck_classifier.py`, lines 6-78

**Add these checks to `classify_bottleneck_type()`:**

```python
def classify_bottleneck_type(metrics):
    """Enhanced classification with new metrics"""

    # Extract all signals
    waiting = metrics.get('num_requests_waiting', 0)
    running = metrics.get('num_requests_running', 1)
    gpu_util = metrics.get('gpu_compute_utilization', 0)
    kv_cache = metrics.get('kv_cache_usage_perc', 0)

    # NEW METRICS
    swapped = metrics.get('num_requests_swapped', 0)
    cpu_cache = metrics.get('cpu_cache_usage_perc', 0)
    preemptions_per_min = metrics.get('preemptions_per_minute', 0)
    scheduler_util = metrics.get('scheduler_utilization_pct')
    max_seqs = metrics.get('max_num_seqs')

    # CRITICAL: CPU swap is active (top priority)
    if swapped > 0 or cpu_cache > 0:
        return "memory_critical_swap"

    # CRITICAL: High preemption rate (thrashing)
    if preemptions_per_min > 10:
        return "scheduler_thrashing"

    # WARNING: Scheduler at capacity
    if scheduler_util is not None and scheduler_util >= 90:
        return "scheduler_saturated"

    # WARNING: Scheduler at capacity (fallback check)
    if max_seqs and running >= max_seqs:
        return "scheduler_saturated"

    # ... rest of existing checks ...

    # (Keep all your current checks below)
```

**Add new diagnostic summaries:**
```python
def get_diagnostic_summary(category, metrics):
    """Enhanced summaries with new metrics"""

    # ... existing summaries ...

    summaries.update({
        "memory_critical_swap": f"CRITICAL: Memory swapping active! {metrics.get('num_requests_swapped', 0)} requests swapped to CPU. CPU cache at {metrics.get('cpu_cache_usage_perc', 0)}%. Latency degraded 10-100x. KV cache at {metrics.get('kv_cache_usage_perc', 0)}%.",

        "scheduler_thrashing": f"CRITICAL: Scheduler thrashing detected. Preemptions: {metrics.get('preemptions_per_minute', 0)}/min (threshold: 10/min). Requests constantly kicked out and restarted. GPU: {metrics.get('gpu_compute_utilization', 0)}%, KV cache: {metrics.get('kv_cache_usage_perc', 0)}%.",

        "scheduler_saturated": f"WARNING: Scheduler at capacity. Running: {metrics.get('num_requests_running', 0)}/{metrics.get('max_num_seqs', 'unknown')} (max_num_seqs). Queue: {metrics.get('num_requests_waiting', 0)} waiting. Latency: {metrics.get('e2e_request_latency_p90', 0):.1f}s.",
    })

    return summaries.get(category, "Unknown bottleneck type")
```

**Add new recommendations:**
```python
def get_recommendation(category, metrics):
    """Enhanced recommendations with new metrics"""

    # ... existing recommendations ...

    recommendations.update({
        "memory_critical_swap": {
            "action": "IMMEDIATE: Scale to 2+ replicas or reduce max_num_seqs",
            "steps": [
                "🚨 CRITICAL: CPU swap = 10-100x latency increase",
                "Option 1 (Recommended): Scale horizontally",
                "  oc scale deployment <name> --replicas=2 -n <namespace>",
                "Option 2: Reduce concurrent load",
                "  oc set env deployment/<name> MAX_NUM_SEQS=<current/2> -n <namespace>",
                "Monitor: KV cache should drop below 70%, swap should become 0"
            ],
            "expected_improvement": f"Swap: {metrics.get('num_requests_swapped', 0)} → 0 | CPU cache: {metrics.get('cpu_cache_usage_perc', 0)}% → 0% | Latency: restore to normal (10-100x speedup)"
        },

        "scheduler_thrashing": {
            "action": "Reduce max_num_seqs to prevent memory pressure",
            "steps": [
                f"Current preemptions: {metrics.get('preemptions_per_minute', 0)}/min (too high)",
                f"Current max_num_seqs: {metrics.get('max_num_seqs', 'unknown')}",
                f"Recommended max_num_seqs: {int(metrics.get('max_num_seqs', 256) * 0.7)} (reduce by 30%)",
                "oc set env deployment/<name> MAX_NUM_SEQS=<new_value> -n <namespace>",
                "Monitor: Preemptions should drop to <2/min"
            ],
            "expected_improvement": f"Preemptions: {metrics.get('preemptions_per_minute', 0)}/min → <2/min | Latency: stabilizes | KV cache: stays below 85%"
        },

        "scheduler_saturated": {
            "action": "Increase max_num_seqs to handle more concurrent requests",
            "steps": [
                f"Current: {metrics.get('num_requests_running', 0)}/{metrics.get('max_num_seqs', 'unknown')} sequences",
                f"Queue: {metrics.get('num_requests_waiting', 0)} waiting",
                f"Recommended max_num_seqs: {int(metrics.get('max_num_seqs', 256) * 1.5)} (increase by 50%)",
                "oc set env deployment/<name> MAX_NUM_SEQS=<new_value> -n <namespace>",
                "Monitor: Queue should drain, watch KV cache (don't exceed 85%)"
            ],
            "expected_improvement": f"Queue: {metrics.get('num_requests_waiting', 0)} → 0 | Scheduler util: {metrics.get('scheduler_utilization_pct', 0):.0f}% → <80%"
        },
    })

    return recommendations.get(category, recommendations["unclear"])
```

---

### 8. Update Dashboard UI (app.py)
**File:** `app.py`, lines 1390-1492

**Add new metric cards after the existing 6:**

```python
# After line 1492, add these new metric cards

st.markdown("#### Advanced Metrics")

adv_metric_cols = st.columns(4)

with adv_metric_cols[0]:
    if current_metrics.get('max_num_seqs'):
        scheduler_util = current_metrics.get('scheduler_utilization_pct', 0)
        if scheduler_util >= 90:
            card_class = "metric-card-critical"
            status = "Saturated"
        elif scheduler_util >= 75:
            card_class = "metric-card-warning"
            status = "High"
        else:
            card_class = "metric-card-healthy"
            status = "Normal"

        st.markdown(f'<div class="{card_class}" style="padding: 1rem; border-radius: 0.5rem;">', unsafe_allow_html=True)
        st.metric("Scheduler",
                  f"{current_metrics['num_requests_running']}/{current_metrics['max_num_seqs']}",
                  help=f"Running sequences / Max concurrent ({scheduler_util:.0f}% utilized)")
        st.caption(status)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("max_num_seqs not exposed")

with adv_metric_cols[1]:
    if current_metrics.get('kv_cache_blocks_total'):
        blocks_used = current_metrics['kv_cache_blocks_used']
        blocks_total = current_metrics['kv_cache_blocks_total']
        block_util = (blocks_used / blocks_total) * 100 if blocks_total > 0 else 0

        if block_util > 85:
            card_class = "metric-card-critical"
            status = "Critical"
        elif block_util > 70:
            card_class = "metric-card-warning"
            status = "Warning"
        else:
            card_class = "metric-card-healthy"
            status = "Healthy"

        st.markdown(f'<div class="{card_class}" style="padding: 1rem; border-radius: 0.5rem;">', unsafe_allow_html=True)
        st.metric("KV Blocks", f"{blocks_used}/{blocks_total}",
                  help=f"Used KV cache blocks ({block_util:.0f}%)")
        st.caption(status)
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("KV blocks not exposed")

with adv_metric_cols[2]:
    preemptions = current_metrics.get('preemptions_per_minute', 0)
    if preemptions > 10:
        card_class = "metric-card-critical"
        status = "Thrashing!"
    elif preemptions > 2:
        card_class = "metric-card-warning"
        status = "High"
    else:
        card_class = "metric-card-healthy"
        status = "Normal"

    st.markdown(f'<div class="{card_class}" style="padding: 1rem; border-radius: 0.5rem;">', unsafe_allow_html=True)
    st.metric("Preemptions", f"{preemptions}/min",
              help="Requests kicked out of batch (indicates memory pressure)")
    st.caption(status)
    st.markdown('</div>', unsafe_allow_html=True)

with adv_metric_cols[3]:
    swapped = current_metrics.get('num_requests_swapped', 0)
    cpu_cache = current_metrics.get('cpu_cache_usage_perc', 0)

    if swapped > 0 or cpu_cache > 0:
        card_class = "metric-card-critical"
        status = "SWAP ACTIVE!"
    else:
        card_class = "metric-card-healthy"
        status = "No Swap"

    st.markdown(f'<div class="{card_class}" style="padding: 1rem; border-radius: 0.5rem;">', unsafe_allow_html=True)
    st.metric("Memory Swap", f"{swapped} req" if swapped > 0 else "None",
              help=f"Requests swapped to CPU memory ({cpu_cache}% CPU cache used)")
    st.caption(status)
    st.markdown('</div>', unsafe_allow_html=True)

# Add critical banner if swap is active
if swapped > 0 or cpu_cache > 0:
    st.markdown(f"""
    <div class="alert-banner alert-critical">
        <strong>🚨 CRITICAL: MEMORY SWAP ACTIVE</strong><br/>
        {swapped} requests swapped to CPU memory. CPU cache at {cpu_cache}%.
        Latency degraded 10-100x. Scale immediately or reduce max_num_seqs.
    </div>
    """, unsafe_allow_html=True)
```

---

## Testing Checklist

After implementing each fix, verify:

- [ ] GPU type shows actual device name (not "Unknown")
- [ ] `max_num_seqs` displays in dashboard
- [ ] Scheduler utilization shows percentage
- [ ] KV cache blocks show absolute counts
- [ ] Preemption rate calculates correctly
- [ ] Swap detection triggers critical alerts
- [ ] Throughput matches vLLM's internal calculation
- [ ] New bottleneck types appear in AI insights

---

## Validation Commands

```bash
# 1. Check vLLM version
oc exec -it <pod> -n <namespace> -- python -c "import vllm; print(vllm.__version__)"

# 2. Verify metrics are exposed
oc exec -it <pod> -n <namespace> -- curl localhost:8080/metrics | grep -E "vllm:(max_num_seqs|gpu_config_device_name|num_gpu_blocks_total)"

# 3. Test metric extraction in Python
python3 << EOF
from vllm_metrics_scraper import VLLMMetricsScraper
scraper = VLLMMetricsScraper(vllm_url="http://localhost:8080")
metrics = scraper.get_metrics()
print(f"GPU Type: {metrics['gpu_type']}")
print(f"Max Seqs: {metrics.get('max_num_seqs')}")
print(f"KV Blocks: {metrics.get('kv_cache_blocks_used')}/{metrics.get('kv_cache_blocks_total')}")
EOF
```

---

## Rollback Plan

If any implementation breaks the dashboard:

```bash
# 1. Revert to last working commit
git log --oneline | head -5  # Find last good commit
git revert <commit-hash>

# 2. Or comment out the new metrics
# In vllm_metrics_scraper.py, wrap new code in try-except:
try:
    metrics['new_metric'] = self.get_metric_value(raw_metrics, 'vllm:new_metric')
except:
    metrics['new_metric'] = None  # Graceful fallback
```

---

## Priority Order

1. **Fix GPU detection** (5 min) - Most visible issue
2. **Add batching metrics** (15 min) - Critical for diagnosis
3. **Add KV blocks** (10 min) - Better memory visibility
4. **Fix throughput** (10 min) - Accuracy improvement
5. **Update classifier** (20 min) - New bottleneck types
6. **Update UI** (20 min) - Show new metrics
7. **Add TPOT** (15 min) - Nice to have
8. **Add caching metrics** (10 min) - Optional

**Total Time: ~2 hours for full implementation**
