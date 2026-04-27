"""
Unified Metrics Service - RHOAI Compatible Metrics Only
Uses ONLY metrics from RHOAI observability manifests
"""

import requests
import re
from datetime import datetime
from typing import Dict, Optional

class MetricsService:
    """
    RHOAI-compatible metrics collection.

    Uses ONLY metrics from RHOAI manifests:
    https://github.com/opendatahub-io/odh-dashboard/tree/main/manifests/observability/rhoai

    Available metrics (8 total):
    1. GPU Utilization (DCGM_FI_DEV_GPU_UTIL) - Generic DCGM metric
    2. GPU Memory Free/Used (DCGM_FI_DEV_FB_FREE/USED) - Generic DCGM metric
    3. E2E Latency (kserve_vllm:e2e_request_latency_seconds)
    4. TTFT (kserve_vllm:time_to_first_token_seconds)
    5. Queue Length (kserve_vllm:request_queue_length)
    6. Requests Running/Waiting (kserve_vllm:num_requests_running/waiting)
    7. Error Rate (kserve_vllm:request_failure_rate)
    8. Success Rate (kserve_vllm:request_success_rate)

    Note: Supports both vllm: and kserve_vllm: prefixes for port-forward compatibility
    """

    def __init__(self, vllm_url="http://localhost:8080", cluster_client=None):
        self.vllm_url = vllm_url
        self.cluster_client = cluster_client
        self.history = {}
        self.timestamps = []
        self._cache = {}
        self._cache_timestamp = None

    def get_metrics(self, namespace="lightspeed-poc", service="vllm"):
        """
        Get current vLLM metrics with intelligent fallback.

        Returns:
            Dict with standardized metric names
        """
        # Try direct vLLM endpoint first
        raw_metrics = self._scrape_vllm_metrics()

        if raw_metrics:
            return self._parse_metrics(raw_metrics, namespace, source="vllm_direct")

        # Fallback: Return empty metrics with connection hint
        return self._empty_metrics(namespace, source="disconnected")

    def _scrape_vllm_metrics(self) -> Optional[Dict]:
        """Scrape and parse Prometheus metrics from vLLM endpoint"""
        try:
            response = requests.get(f"{self.vllm_url}/metrics", timeout=5)
            if response.status_code != 200:
                return None

            metrics_text = response.text
            metrics = {}

            # Parse Prometheus text format
            for line in metrics_text.split('\n'):
                # Skip comments and empty lines
                if line.startswith('#') or not line.strip():
                    continue

                # Extract metric name and value
                match = re.match(r'([a-zA-Z_:][a-zA-Z0-9_:]*)\{?(.*?)\}?\s+([0-9.e+-]+)', line)
                if match:
                    metric_name = match.group(1)
                    labels_str = match.group(2)
                    value = float(match.group(3))

                    # Parse labels
                    labels = {}
                    if labels_str:
                        for label_match in re.finditer(r'(\w+)="([^"]*)"', labels_str):
                            labels[label_match.group(1)] = label_match.group(2)

                    # Store metric with labels
                    if metric_name not in metrics:
                        metrics[metric_name] = []
                    metrics[metric_name].append({'value': value, 'labels': labels})

            return metrics

        except Exception as e:
            print(f"Error scraping vLLM metrics: {e}")
            return None

    def _get_metric_value(self, raw_metrics: Dict, metric_name: str, label_filters: Optional[Dict] = None) -> Optional[float]:
        """Extract a single metric value with optional label filtering - RHOAI compatible only"""

        # RHOAI uses kserve_vllm: prefix exclusively
        # Also support native vllm: for direct port-forward compatibility
        for prefix in ['kserve_vllm:', 'vllm:']:
            full_name = metric_name if metric_name.startswith(prefix) else f"{prefix}{metric_name.replace('vllm:', '').replace('kserve_vllm:', '')}"

            if full_name not in raw_metrics:
                continue

            metrics_list = raw_metrics[full_name]

            # If no label filters, return first value
            if not label_filters:
                return metrics_list[0]['value'] if metrics_list else None

            # Filter by labels
            for metric in metrics_list:
                labels = metric['labels']
                match = all(labels.get(k) == v for k, v in label_filters.items())
                if match:
                    return metric['value']

        return None

    def _parse_metrics(self, raw_metrics: Dict, namespace: str, source: str) -> Dict:
        """Parse raw Prometheus metrics into standardized format"""
        metrics = {}
        metrics['source'] = source
        metrics['namespace'] = namespace

        # Extract model name from labels
        model_name = 'unknown'
        for prefix in ['vllm:num_requests_running', 'kserve_vllm:num_requests_running']:
            if prefix in raw_metrics:
                for metric in raw_metrics[prefix]:
                    model_name = metric['labels'].get('model_name', 'unknown')
                    break
                if model_name != 'unknown':
                    break

        metrics['model_name'] = model_name

        # GPU type detection - Try cluster first, then memory inference
        gpu_type = "Unknown GPU"
        if self.cluster_client and hasattr(self.cluster_client, 'get_gpu_type_from_nodes'):
            try:
                if self.cluster_client.is_logged_in():
                    gpu_type = self.cluster_client.get_gpu_type_from_nodes()
            except:
                pass

        # Fallback to memory-based inference if cluster didn't work
        if gpu_type == "Unknown" or gpu_type == "Unknown GPU":
            gpu_memory_bytes = self._get_metric_value(raw_metrics, 'vllm:gpu_config_total_memory_bytes')
            if gpu_memory_bytes:
                gpu_memory_gb = gpu_memory_bytes / (1024**3)
                if 14 <= gpu_memory_gb < 20:
                    gpu_type = "NVIDIA T4 (16GB)"
                elif 22 <= gpu_memory_gb < 26:
                    gpu_type = "NVIDIA A10G (24GB)"
                elif 38 <= gpu_memory_gb < 50:
                    gpu_type = "NVIDIA A100 (40GB)"
                elif 78 <= gpu_memory_gb < 90:
                    gpu_type = "NVIDIA A100 (80GB)"
                else:
                    gpu_type = f"GPU ({gpu_memory_gb:.0f}GB)"

        metrics['gpu_type'] = gpu_type

        # 1. GPU Utilization (DCGM metric - generic GPU compute %)
        gpu_util = self._get_metric_value(raw_metrics, 'DCGM_FI_DEV_GPU_UTIL')

        # Fallback: if DCGM not available, estimate from KV cache usage
        if gpu_util is None:
            gpu_cache = self._get_metric_value(raw_metrics, 'gpu_cache_usage_perc')
            if gpu_cache is not None:
                # KV cache % as proxy for GPU memory usage (rough approximation)
                metrics['gpu_utilization'] = int(gpu_cache * 100)
            else:
                metrics['gpu_utilization'] = 0
        else:
            metrics['gpu_utilization'] = int(gpu_util)

        metrics['gpu_compute_utilization'] = metrics['gpu_utilization']

        # 2. GPU Memory (DCGM metrics or fallback to vLLM native)
        gpu_mem_free = self._get_metric_value(raw_metrics, 'DCGM_FI_DEV_FB_FREE')
        gpu_mem_used = self._get_metric_value(raw_metrics, 'DCGM_FI_DEV_FB_USED')

        if gpu_mem_free is not None and gpu_mem_used is not None:
            total_mem = gpu_mem_free + gpu_mem_used
            metrics['kv_cache_usage_perc'] = int((gpu_mem_used / total_mem) * 100) if total_mem > 0 else 0
        else:
            # Fallback: use native vLLM gpu_cache_usage_perc
            gpu_cache = self._get_metric_value(raw_metrics, 'gpu_cache_usage_perc')
            if gpu_cache is not None:
                metrics['kv_cache_usage_perc'] = int(gpu_cache * 100)
            else:
                metrics['kv_cache_usage_perc'] = 0

        # 6. Requests Running/Waiting (kserve_vllm or vllm prefix)
        running = self._get_metric_value(raw_metrics, 'num_requests_running')
        metrics['num_requests_running'] = int(running) if running is not None else 0

        waiting = self._get_metric_value(raw_metrics, 'num_requests_waiting')
        metrics['num_requests_waiting'] = int(waiting) if waiting is not None else 0

        # 5. Queue Length
        queue_length = self._get_metric_value(raw_metrics, 'request_queue_length')
        metrics['request_queue_length'] = int(queue_length) if queue_length is not None else metrics['num_requests_waiting']

        # 3. E2E Latency (histogram - calculate P90)
        metrics['e2e_request_latency_p90'] = self._estimate_percentile(
            raw_metrics, 'e2e_request_latency_seconds', 0.9
        )

        # 4. TTFT (histogram - calculate P90)
        metrics['time_to_first_token_p90'] = self._estimate_percentile(
            raw_metrics, 'time_to_first_token_seconds', 0.9
        )

        # 7 & 8. Success/Error Rates (RHOAI provides these as gauges)
        success_rate = self._get_metric_value(raw_metrics, 'request_success_rate')
        error_rate = self._get_metric_value(raw_metrics, 'request_failure_rate')

        if success_rate is not None:
            metrics['request_success_rate'] = round(success_rate, 1)
        else:
            # Fallback: calculate from totals if gauges not available
            success_total = self._get_metric_value(raw_metrics, 'request_success_total')
            failure_total = self._get_metric_value(raw_metrics, 'request_failure_total')

            if success_total is not None and success_total > 0:
                total = success_total + (failure_total if failure_total else 0)
                metrics['request_success_rate'] = round((success_total / total) * 100, 1) if total > 0 else 100.0
            else:
                metrics['request_success_rate'] = 100.0

        if error_rate is not None:
            metrics['request_failure_rate'] = round(error_rate, 1)
        else:
            # Derive from success rate
            metrics['request_failure_rate'] = round(100 - metrics['request_success_rate'], 1)

        # Throughput calculation (for display, not in RHOAI core 8)
        gen_tokens_total = self._get_metric_value(raw_metrics, 'generation_tokens_total')

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

        # Token totals (for display)
        prompt_tokens = self._get_metric_value(raw_metrics, 'prompt_tokens_total')
        metrics['prompt_tokens_total'] = int(prompt_tokens) if prompt_tokens is not None else 0
        metrics['generation_tokens_total'] = int(gen_tokens_total) if gen_tokens_total is not None else 0

        # Not available in RHOAI - set to 0
        metrics['prompt_tokens_p50'] = 0
        metrics['prompt_tokens_p90'] = 0
        metrics['prompt_tokens_p99'] = 0
        metrics['generation_tokens_p50'] = 0
        metrics['generation_tokens_p90'] = 0
        metrics['generation_tokens_p99'] = 0

        # RPS (approximated)
        metrics['requests_per_second'] = 0.0

        # Defaults
        metrics['cpu_utilization_pct'] = 0
        metrics['replica_count'] = 1
        metrics['batch_size'] = None
        metrics['max_num_seqs'] = None
        metrics['gpu_architecture'] = 'Unknown'
        metrics['cuda_version'] = 'Unknown'
        metrics['compute_capability'] = 'Unknown'

        # Update history
        self.timestamps.append(datetime.now().strftime("%H:%M:%S"))
        for key, value in metrics.items():
            if key not in ['namespace', 'model_name', 'replica_count', 'gpu_type', 'source']:
                if key not in self.history:
                    self.history[key] = []
                self.history[key].append(value)

        # Keep only last 15 data points
        if len(self.timestamps) > 15:
            self.timestamps = self.timestamps[-15:]
            for key in self.history:
                self.history[key] = self.history[key][-15:]

        return metrics

    def _estimate_percentile(self, raw_metrics: Dict, metric_prefix: str, percentile: float) -> float:
        """Estimate percentile from histogram buckets"""
        bucket_metric = f"{metric_prefix}_bucket"
        count_metric = f"{metric_prefix}_count"

        # Try both prefixes
        bucket_data = None
        count_data = None

        for prefix in ['', 'kserve_']:
            full_bucket = f"{prefix}{bucket_metric}"
            full_count = f"{prefix}{count_metric}"

            if full_bucket in raw_metrics:
                bucket_data = raw_metrics[full_bucket]
                if full_count in raw_metrics:
                    count_data = self._get_metric_value(raw_metrics, full_count)
                break

        if not bucket_data:
            return 0.0

        # Get total count
        total_count = count_data if count_data else 0
        if not total_count or total_count == 0:
            return 0.0

        # Find the bucket containing the percentile
        target_count = total_count * percentile
        sorted_buckets = sorted(
            [b for b in bucket_data if 'le' in b['labels']],
            key=lambda x: float(x['labels']['le']) if x['labels']['le'] != '+Inf' else float('inf')
        )

        for bucket in sorted_buckets:
            if bucket['value'] >= target_count:
                le_value = bucket['labels']['le']
                if le_value == '+Inf':
                    return float('inf')
                return round(float(le_value), 2)

        return 0.0

    def _empty_metrics(self, namespace: str, source: str) -> Dict:
        """Return empty metrics structure with connection hint"""
        return {
            'source': source,
            'namespace': namespace,
            'model_name': 'unknown',
            'gpu_type': 'Unknown (disconnected)',
            'kv_cache_usage_perc': 0,
            'gpu_compute_utilization': 0,
            'gpu_utilization': 0,
            'num_requests_running': 0,
            'num_requests_waiting': 0,
            'tokens_per_second': 0,
            'prompt_tokens_total': 0,
            'generation_tokens_total': 0,
            'e2e_request_latency_p90': 0.0,
            'time_to_first_token_p90': 0.0,
            'prompt_tokens_p50': 0,
            'prompt_tokens_p90': 0,
            'prompt_tokens_p99': 0,
            'generation_tokens_p50': 0,
            'generation_tokens_p90': 0,
            'generation_tokens_p99': 0,
            'request_success_rate': 100.0,
            'request_failure_rate': 0.0,
            'requests_per_second': 0.0,
            'cpu_utilization_pct': 0,
            'replica_count': 1,
            'batch_size': None,
            'max_num_seqs': None,
            'gpu_architecture': 'Unknown',
            'cuda_version': 'Unknown',
            'compute_capability': 'Unknown'
        }

    def is_available(self) -> bool:
        """Check if vLLM metrics endpoint is reachable"""
        try:
            response = requests.get(f"{self.vllm_url}/health", timeout=2)
            return response.status_code == 200
        except:
            return False
