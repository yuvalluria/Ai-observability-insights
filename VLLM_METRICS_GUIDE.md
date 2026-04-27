# vLLM Production Metrics - Implementation Guide

## Overview
This guide covers the critical vLLM metrics missing from your current dashboard and how to integrate them for production-grade observability.

---

## Metric Categories

### 1. Scheduler & Batching Metrics

#### `vllm:max_num_seqs`
- **Type:** Gauge
- **Description:** Maximum number of sequences that can run concurrently
- **Usage:** Compare with `num_requests_running` to detect capacity limits
- **Alert:** If `num_requests_running == max_num_seqs` for >2 minutes → increase `max_num_seqs`

```python
# In vllm_metrics_scraper.py
max_seqs = self.get_metric_value(raw_metrics, 'vllm:max_num_seqs')
metrics['max_num_seqs'] = int(max_seqs) if max_seqs else None

# Calculate scheduler pressure
if max_seqs and metrics['num_requests_running'] >= max_seqs * 0.9:
    # Scheduler is at 90%+ capacity
    metrics['scheduler_pressure'] = 'high'
```

#### `vllm:num_preemptions_total`
- **Type:** Counter
- **Description:** Total number of requests preempted (kicked out of batch)
- **Usage:** High preemption rate = thrashing, memory pressure
- **Alert:** If rate >10/min → OOM risk or `max_num_seqs` too high

```python
preemptions = self.get_metric_value(raw_metrics, 'vllm:num_preemptions_total')
metrics['num_preemptions_total'] = int(preemptions) if preemptions else 0

# Calculate preemption rate (requires history)
if hasattr(self, 'last_preemptions'):
    time_diff = current_time - self.last_preemption_time
    if time_diff > 0:
        preemption_rate = (preemptions - self.last_preemptions) / (time_diff / 60)
        metrics['preemptions_per_minute'] = round(preemption_rate, 1)
```

#### `vllm:avg_generation_throughput_toks_per_s`
- **Type:** Gauge
- **Description:** Average per-request decode speed (more accurate than total/time)
- **Usage:** Detect decode inefficiency, compare to GPU baseline
- **Expected Values:**
  - A10G: 15-30 tok/s per request (decode-bound)
  - A100-40GB: 30-60 tok/s per request
  - H100: 80-150 tok/s per request

```python
avg_throughput = self.get_metric_value(raw_metrics, 'vllm:avg_generation_throughput_toks_per_s')
if avg_throughput:
    metrics['avg_decode_speed_per_request'] = round(avg_throughput, 1)

    # Compare to expected baseline
    gpu_type = metrics.get('gpu_type', '')
    if 'A10G' in gpu_type and avg_throughput < 15:
        metrics['decode_performance'] = 'degraded'
    elif 'A100' in gpu_type and avg_throughput < 30:
        metrics['decode_performance'] = 'degraded'
    else:
        metrics['decode_performance'] = 'normal'
```

#### `vllm:avg_prompt_throughput_toks_per_s`
- **Type:** Gauge
- **Description:** Prefill speed (tokens processed during TTFT phase)
- **Usage:** Diagnose slow prefill (should be 1000-5000 tok/s on modern GPUs)
- **Alert:** If <500 tok/s → prefill bottleneck

```python
prefill_throughput = self.get_metric_value(raw_metrics, 'vllm:avg_prompt_throughput_toks_per_s')
if prefill_throughput:
    metrics['avg_prefill_throughput'] = round(prefill_throughput, 1)
```

---

### 2. KV Cache Block Metrics (PagedAttention)

#### `vllm:num_gpu_blocks_total`
- **Type:** Gauge
- **Description:** Total number of KV cache blocks allocated in GPU memory
- **Usage:** Understand absolute KV cache capacity (not just percentage)

```python
total_blocks = self.get_metric_value(raw_metrics, 'vllm:num_gpu_blocks_total')
free_blocks = self.get_metric_value(raw_metrics, 'vllm:num_gpu_blocks_free')

if total_blocks:
    metrics['kv_cache_blocks_total'] = int(total_blocks)
    metrics['kv_cache_blocks_free'] = int(free_blocks) if free_blocks else 0
    metrics['kv_cache_blocks_used'] = int(total_blocks - (free_blocks or 0))

    # This is more accurate than gpu_cache_usage_perc
    if total_blocks > 0:
        metrics['kv_cache_block_utilization_pct'] = round(
            (metrics['kv_cache_blocks_used'] / total_blocks) * 100, 1
        )
```

**Block size context:**
- Each block typically stores 16-32 tokens (depends on `block_size` config)
- A100-40GB with Llama-7B: ~4000-8000 blocks
- A10G-24GB with Llama-7B: ~2000-4000 blocks

#### `vllm:cpu_cache_usage_perc`
- **Type:** Gauge
- **Description:** CPU swap space usage (when GPU KV cache is full)
- **Usage:** **CRITICAL ALERT** - CPU cache usage = severe performance degradation
- **Alert:** If >0% → immediate action needed (scale or reduce load)

```python
cpu_cache = self.get_metric_value(raw_metrics, 'vllm:cpu_cache_usage_perc')
if cpu_cache is not None:
    metrics['cpu_cache_usage_perc'] = int(cpu_cache * 100)

    # CPU swap is a critical condition
    if metrics['cpu_cache_usage_perc'] > 0:
        metrics['memory_swap_active'] = True
        metrics['bottleneck_override'] = 'memory_critical_swap'
```

#### `vllm:num_requests_swapped`
- **Type:** Gauge
- **Description:** Number of requests currently swapped to CPU memory
- **Usage:** Even 1 swapped request = 10-100x latency increase
- **Alert:** If >0 → CRITICAL, scale immediately

```python
swapped = self.get_metric_value(raw_metrics, 'vllm:num_requests_swapped')
metrics['num_requests_swapped'] = int(swapped) if swapped else 0
```

---

### 3. Request Lifecycle Metrics

#### `vllm:time_per_output_token_seconds`
- **Type:** Histogram
- **Description:** Time to generate each token during decode (TPOT)
- **Usage:** More accurate than `(latency - TTFT) / num_tokens`
- **Expected Values:**
  - A10G: 30-70ms per token (14-33 tok/s)
  - A100: 15-35ms per token (28-66 tok/s)

```python
tpot_p50 = self._estimate_percentile(raw_metrics, 'vllm:time_per_output_token_seconds', 0.5)
tpot_p90 = self._estimate_percentile(raw_metrics, 'vllm:time_per_output_token_seconds', 0.9)

metrics['time_per_output_token_p50'] = round(tpot_p50 * 1000, 1)  # Convert to ms
metrics['time_per_output_token_p90'] = round(tpot_p90 * 1000, 1)
```

#### `vllm:inter_token_latency_seconds`
- **Type:** Histogram
- **Description:** Time between consecutive tokens (includes scheduling overhead)
- **Usage:** Detect jitter, batching inefficiency
- **Alert:** If P90 > 2x P50 → scheduling issues

```python
itl_p50 = self._estimate_percentile(raw_metrics, 'vllm:inter_token_latency_seconds', 0.5)
itl_p90 = self._estimate_percentile(raw_metrics, 'vllm:inter_token_latency_seconds', 0.9)

metrics['inter_token_latency_p50'] = round(itl_p50 * 1000, 1)
metrics['inter_token_latency_p90'] = round(itl_p90 * 1000, 1)

# Detect jitter
if itl_p50 > 0 and itl_p90 / itl_p50 > 2:
    metrics['token_latency_jitter'] = 'high'
```

#### `vllm:num_generation_tokens_from_cache_total`
- **Type:** Counter
- **Description:** Tokens served from prefix cache (automatic prompt caching)
- **Usage:** Measure prefix caching effectiveness
- **Expected:** If enabled, 20-60% cache hit rate for repeated prompts

```python
cached_tokens = self.get_metric_value(raw_metrics, 'vllm:num_generation_tokens_from_cache_total')
total_gen_tokens = self.get_metric_value(raw_metrics, 'vllm:generation_tokens_total')

if cached_tokens and total_gen_tokens and total_gen_tokens > 0:
    cache_hit_rate = (cached_tokens / total_gen_tokens) * 100
    metrics['prefix_cache_hit_rate_pct'] = round(cache_hit_rate, 1)
```

---

### 4. Hardware & Config Metrics

#### `vllm:gpu_config_device_name`
- **Type:** Info
- **Description:** GPU model name (e.g., "NVIDIA A10G", "Tesla T4")
- **Usage:** **THIS IS WHY YOUR GPU DETECTION FAILS**

```python
# Priority 1: Direct device name
device_name = self.get_metric_value(raw_metrics, 'vllm:gpu_config_device_name')
if device_name:
    metrics['gpu_type'] = device_name
else:
    # Fallback to your current memory-based inference
    metrics['gpu_type'] = self._infer_gpu_from_memory(raw_metrics)
```

#### `vllm:gpu_config_num_devices`
- **Type:** Gauge
- **Description:** Number of GPUs used by this vLLM instance
- **Usage:** Detect tensor parallelism, pipeline parallelism

```python
num_gpus = self.get_metric_value(raw_metrics, 'vllm:gpu_config_num_devices')
metrics['num_gpus'] = int(num_gpus) if num_gpus else 1

# Infer parallelism strategy
if metrics['num_gpus'] > 1:
    # Check for tensor parallelism env var or model size
    metrics['parallelism_enabled'] = True
```

#### `vllm:max_num_batched_tokens`
- **Type:** Gauge
- **Description:** Maximum tokens that can be in-flight in a single batch
- **Usage:** Compare with actual token count to detect configuration limits

```python
max_batched = self.get_metric_value(raw_metrics, 'vllm:max_num_batched_tokens')
metrics['max_num_batched_tokens'] = int(max_batched) if max_batched else None

# Calculate current batch token count
if metrics['num_requests_running'] > 0:
    avg_tokens_per_req = metrics.get('generation_tokens_p50', 128)
    current_batch_tokens = metrics['num_requests_running'] * avg_tokens_per_req

    if max_batched and current_batch_tokens >= max_batched * 0.9:
        metrics['batch_token_limit_pressure'] = 'high'
```

#### `vllm:max_model_len`
- **Type:** Gauge
- **Description:** Maximum sequence length supported by the model
- **Usage:** Detect requests approaching context limit

```python
max_len = self.get_metric_value(raw_metrics, 'vllm:max_model_len')
metrics['max_model_len'] = int(max_len) if max_len else None

# Alert on context overflow risk
if max_len:
    max_observed_tokens = metrics.get('prompt_tokens_p99', 0) + metrics.get('generation_tokens_p99', 0)
    if max_observed_tokens >= max_len * 0.9:
        metrics['context_limit_risk'] = 'high'
```

---

## Implementation Priority

### Phase 1: Critical (This Week)
1. Fix GPU type detection (`vllm:gpu_config_device_name`)
2. Add batching visibility (`max_num_seqs`, `num_preemptions_total`)
3. Add KV cache blocks (`num_gpu_blocks_total`, `num_gpu_blocks_free`)
4. Add swap detection (`cpu_cache_usage_perc`, `num_requests_swapped`)

### Phase 2: High Priority (Next Sprint)
5. Add throughput accuracy (`avg_generation_throughput_toks_per_s`)
6. Add TPOT metrics (`time_per_output_token_seconds`)
7. Add prefix caching metrics (`num_generation_tokens_from_cache_total`)
8. Add config validation (`max_num_batched_tokens`, `max_model_len`)

### Phase 3: Nice to Have (Future)
9. Inter-token latency jitter detection
10. Per-model breakdown (multi-LoRA scenarios)
11. Request queueing time distribution
12. Chunked prefill metrics (if using disaggregated prefill)

---

## Dashboard Updates

### New Metric Cards to Add

```python
# In app.py, add these to the metric_cols section

# Scheduler Utilization
scheduler_util = (current_metrics['num_requests_running'] /
                  current_metrics['max_num_seqs']) * 100 if current_metrics.get('max_num_seqs') else 0
st.metric("Scheduler Utilization", f"{scheduler_util:.0f}%",
          help=f"Running: {current_metrics['num_requests_running']} / Max: {current_metrics.get('max_num_seqs', 'N/A')}")

# KV Cache Blocks
if current_metrics.get('kv_cache_blocks_total'):
    st.metric("KV Blocks Used",
              f"{current_metrics['kv_cache_blocks_used']}/{current_metrics['kv_cache_blocks_total']}",
              help="Absolute KV cache block count (more precise than %)")

# Preemption Rate
if current_metrics.get('preemptions_per_minute'):
    preemption_rate = current_metrics['preemptions_per_minute']
    if preemption_rate > 10:
        st.metric("Preemptions", f"{preemption_rate:.1f}/min", delta="Critical", delta_color="inverse")
    else:
        st.metric("Preemptions", f"{preemption_rate:.1f}/min")

# Memory Swap Alert (CRITICAL)
if current_metrics.get('num_requests_swapped', 0) > 0:
    st.error(f"🚨 MEMORY SWAP ACTIVE: {current_metrics['num_requests_swapped']} requests swapped to CPU")
```

### New Alert Rules

```python
# In bottleneck_classifier.py, add these checks

# CRITICAL: CPU swap is active
if metrics.get('num_requests_swapped', 0) > 0:
    return "memory_critical_swap"

# CRITICAL: High preemption rate
if metrics.get('preemptions_per_minute', 0) > 10:
    return "scheduler_thrashing"

# WARNING: Scheduler at capacity
if metrics.get('max_num_seqs'):
    scheduler_util = metrics['num_requests_running'] / metrics['max_num_seqs']
    if scheduler_util >= 0.9:
        return "scheduler_saturated"

# INFO: Prefix caching working well
if metrics.get('prefix_cache_hit_rate_pct', 0) > 40:
    return "caching_effective"
```

---

## Testing the Metrics

### 1. Verify metrics are exposed by vLLM

```bash
# SSH into vLLM pod
oc exec -it <vllm-pod> -n <namespace> -- bash

# Check /metrics endpoint
curl localhost:8080/metrics | grep -E "vllm:(max_num_seqs|num_preemptions|gpu_config_device_name)"
```

### 2. Test metric extraction

```python
# In Python REPL
from vllm_metrics_scraper import VLLMMetricsScraper

scraper = VLLMMetricsScraper(vllm_url="http://localhost:8080")
raw = scraper.scrape_metrics()

# Check if metrics exist
print("max_num_seqs:", raw.get('vllm:max_num_seqs'))
print("gpu_device_name:", raw.get('vllm:gpu_config_device_name'))
print("total_blocks:", raw.get('vllm:num_gpu_blocks_total'))
```

### 3. Validate calculations

```python
# Verify KV cache block utilization
metrics = scraper.get_metrics()
print(f"KV Cache %: {metrics['kv_cache_usage_perc']}%")
print(f"KV Blocks: {metrics['kv_cache_blocks_used']}/{metrics['kv_cache_blocks_total']}")
print(f"Match: {metrics['kv_cache_usage_perc'] == (metrics['kv_cache_blocks_used']/metrics['kv_cache_blocks_total'])*100}")
```

---

## vLLM Version Compatibility

| Metric | vLLM v0.4.x | vLLM v0.5.x | vLLM v0.6.x+ |
|--------|-------------|-------------|--------------|
| `gpu_cache_usage_perc` | ✅ | ✅ | ✅ |
| `num_preemptions_total` | ✅ | ✅ | ✅ |
| `gpu_config_device_name` | ❌ | ✅ | ✅ |
| `num_gpu_blocks_total` | ✅ | ✅ | ✅ |
| `avg_generation_throughput_toks_per_s` | ❌ | ✅ | ✅ |
| `time_per_output_token_seconds` | ❌ | ❌ | ✅ |
| `num_generation_tokens_from_cache_total` | ❌ | ❌ | ✅ (v0.6.2+) |

**Check your vLLM version:**
```bash
oc exec <vllm-pod> -n <namespace> -- python -c "import vllm; print(vllm.__version__)"
```

---

## Common Issues & Fixes

### Issue: "Metric not found in raw_metrics"
**Cause:** vLLM version doesn't expose that metric
**Fix:** Check version compatibility table above, upgrade vLLM if needed

### Issue: "gpu_config_device_name returns None"
**Cause:** vLLM <0.5.0 doesn't expose device name
**Fix:** Use memory-based inference as fallback (already implemented)

### Issue: "KV cache blocks show 0"
**Cause:** Metric name changed between versions
**Fix:** Try both `vllm:num_gpu_blocks` and `vllm:gpu_cache_num_blocks`

---

## Next Steps

1. **Audit vLLM version** - Run `vllm --version` on your pods
2. **Test metric availability** - Check `/metrics` endpoint for new metrics
3. **Update `vllm_metrics_scraper.py`** - Add Phase 1 metrics (GPU type, batching, KV blocks)
4. **Update `bottleneck_classifier.py`** - Add new alert rules (swap, thrashing, saturation)
5. **Update dashboard UI** - Add new metric cards and visualizations
6. **Validate accuracy** - Compare dashboard readings with `kubectl top` and Prometheus

---

## References

- vLLM Metrics Documentation: https://docs.vllm.ai/en/latest/serving/metrics.html
- PagedAttention Paper: https://arxiv.org/abs/2309.06180
- vLLM Performance Tuning: https://docs.vllm.ai/en/latest/models/performance.html
