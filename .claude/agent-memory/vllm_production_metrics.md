---
name: vLLM Production Metrics Knowledge
description: Critical vLLM metrics missing from dashboard and their diagnostic value for production deployments
type: reference
---

# vLLM Production Metrics - Memory Note

## Key Discovery: Dashboard Missing 15+ Critical Metrics

User's dashboard monitors basic vLLM metrics (KV cache %, latency, throughput) but lacks production-grade observability needed for diagnosing real bottlenecks.

## Critical Missing Metrics by Category

### 1. Scheduler & Batching (Most Critical)
- `vllm:max_num_seqs` - Max concurrent sequences (diagnose capacity limits)
- `vllm:num_preemptions_total` - Request evictions (indicates thrashing)
- `vllm:avg_generation_throughput_toks_per_s` - Per-request decode speed (more accurate than manual calc)
- `vllm:avg_prompt_throughput_toks_per_s` - Prefill speed (should be 1000-5000 tok/s)

**Why critical:** Bottleneck classifier detects "gpu_underutilization" but can't diagnose root cause without these.

### 2. KV Cache Blocks (PagedAttention)
- `vllm:num_gpu_blocks_total` - Absolute block count (not just %)
- `vllm:num_gpu_blocks_free` - Available blocks
- `vllm:cpu_cache_usage_perc` - CPU swap usage (CRITICAL ALERT)
- `vllm:num_requests_swapped` - Requests in CPU memory (10-100x latency degradation)

**Why critical:** "45% KV cache" is meaningless without knowing block count. Swap detection is missing entirely.

### 3. Request Lifecycle
- `vllm:time_per_output_token_seconds` - TPOT (per-token decode time)
- `vllm:inter_token_latency_seconds` - Jitter detection
- `vllm:num_generation_tokens_from_cache_total` - Prefix caching effectiveness

### 4. Hardware & Config
- `vllm:gpu_config_device_name` - **WHY GPU TYPE SHOWS "UNKNOWN"**
- `vllm:gpu_config_num_devices` - Multi-GPU detection
- `vllm:max_num_batched_tokens` - Batch token limit
- `vllm:max_model_len` - Context length limit

## Specific Bugs Found

### Bug #1: GPU Type Detection Fails
**Location:** `vllm_metrics_scraper.py` lines 98-143
**Root Cause:** Only uses memory-based inference, doesn't check `vllm:gpu_config_device_name` metric
**Fix:** Add priority-based detection: device_name → metric labels → cluster → memory inference

### Bug #2: Throughput Inaccurate
**Location:** `vllm_metrics_scraper.py` lines 161-180
**Root Cause:** Manual rate calculation includes idle time, doesn't account for in-flight tokens
**Fix:** Use `vllm:avg_generation_throughput_toks_per_s` (vLLM's internal calculation)

### Bug #3: No Batching Visibility
**Impact:** Can't answer "What's my batch size?" or "Is continuous batching working?"
**Fix:** Add `max_num_seqs`, calculate scheduler utilization, track preemptions

## Expected Performance Baselines (for Alerts)

### A10G (24GB)
- Decode speed: 15-30 tok/s per request
- Prefill: 1000-2000 tok/s
- KV cache blocks: ~2000-4000

### A100-40GB
- Decode speed: 30-60 tok/s per request
- Prefill: 2000-4000 tok/s
- KV cache blocks: ~4000-8000

### H100-80GB
- Decode speed: 80-150 tok/s per request
- Prefill: 5000-10000 tok/s
- KV cache blocks: ~8000-16000

## New Alert Rules to Add

1. **CRITICAL:** `num_requests_swapped > 0` → CPU swap active (10-100x latency)
2. **CRITICAL:** `preemptions_per_minute > 10` → Scheduler thrashing
3. **WARNING:** `scheduler_utilization >= 90%` → At capacity, increase max_num_seqs
4. **WARNING:** `kv_cache_blocks_free < 10%` → Memory pressure imminent
5. **INFO:** `prefix_cache_hit_rate > 40%` → Caching effective

## Implementation Priority

**Phase 1 (Critical - This Week):**
1. Fix GPU type detection (5 min)
2. Add batching metrics (max_num_seqs, preemptions) (15 min)
3. Add KV cache blocks (10 min)
4. Add swap detection (critical alerts) (10 min)

**Phase 2 (High Priority - Next Sprint):**
5. Fix throughput accuracy (10 min)
6. Add TPOT metrics (15 min)
7. Add prefix caching metrics (10 min)
8. Update bottleneck classifier (20 min)
9. Update dashboard UI (20 min)

**Total: ~2 hours for full production-grade observability**

## vLLM Version Compatibility

- `gpu_config_device_name` - vLLM v0.5.0+
- `avg_generation_throughput_toks_per_s` - vLLM v0.5.0+
- `time_per_output_token_seconds` - vLLM v0.6.0+
- `num_generation_tokens_from_cache_total` - vLLM v0.6.2+

User should check vLLM version: `oc exec <pod> -- python -c "import vllm; print(vllm.__version__)"`

## References
- Full implementation guide: `IMPLEMENTATION_CHECKLIST.md`
- Metric documentation: `VLLM_METRICS_GUIDE.md`
- vLLM docs: https://docs.vllm.ai/en/latest/serving/metrics.html
