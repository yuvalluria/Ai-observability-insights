"""
Direct vLLM metrics scraper - parses /metrics endpoint without Prometheus
"""

import requests
import re
from datetime import datetime

class VLLMMetricsScraper:
    """Scrapes metrics directly from vLLM /metrics endpoint"""

    def __init__(self, vllm_url="http://localhost:8080"):
        self.base_url = vllm_url
        self.history = {}
        self.timestamps = []

    def scrape_metrics(self):
        """Scrape and parse Prometheus metrics from vLLM"""
        try:
            response = requests.get(f"{self.base_url}/metrics", timeout=5)
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

    def get_metric_value(self, raw_metrics, metric_name, label_filters=None):
        """Extract a single metric value with optional label filtering"""
        if not raw_metrics or metric_name not in raw_metrics:
            return None

        metrics_list = raw_metrics[metric_name]

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

    def get_metrics(self, namespace="lightspeed-poc", service="vllm"):
        """Get formatted metrics compatible with PrometheusClient interface"""
        raw_metrics = self.scrape_metrics()

        if not raw_metrics:
            # Return empty metrics if scraping failed
            return self._empty_metrics(namespace)

        metrics = {}

        # Extract model name from labels
        model_name = 'unknown'
        if 'vllm:num_requests_running' in raw_metrics:
            for metric in raw_metrics['vllm:num_requests_running']:
                model_name = metric['labels'].get('model_name', 'unknown')
                break

        metrics['namespace'] = namespace
        metrics['model_name'] = model_name

        # GPU type from memory
        gpu_memory_bytes = self.get_metric_value(raw_metrics, 'vllm:gpu_config_total_memory_bytes')
        if gpu_memory_bytes:
            gpu_memory_gb = gpu_memory_bytes / (1024**3)
            if 14 <= gpu_memory_gb < 20:
                metrics['gpu_type'] = "NVIDIA T4 (16GB)"
            elif 22 <= gpu_memory_gb < 26:
                metrics['gpu_type'] = "NVIDIA A10G (24GB)"
            elif 38 <= gpu_memory_gb < 50:
                metrics['gpu_type'] = "NVIDIA A100 (40GB)"
            elif 78 <= gpu_memory_gb < 90:
                metrics['gpu_type'] = "NVIDIA A100 (80GB)"
            else:
                metrics['gpu_type'] = f"GPU ({gpu_memory_gb:.0f}GB)"
        else:
            metrics['gpu_type'] = "Unknown GPU"

        # KV cache usage
        kv_cache = self.get_metric_value(raw_metrics, 'vllm:gpu_cache_usage_perc')
        metrics['kv_cache_usage_perc'] = int(kv_cache * 100) if kv_cache is not None else 0

        # Use KV cache as GPU utilization (vLLM doesn't expose compute directly)
        metrics['gpu_compute_utilization'] = metrics['kv_cache_usage_perc']
        metrics['gpu_utilization'] = metrics['kv_cache_usage_perc']

        # Running and waiting requests
        running = self.get_metric_value(raw_metrics, 'vllm:num_requests_running')
        metrics['num_requests_running'] = int(running) if running is not None else 0

        waiting = self.get_metric_value(raw_metrics, 'vllm:num_requests_waiting')
        metrics['num_requests_waiting'] = int(waiting) if waiting is not None else 0

        # Throughput - use generation tokens rate
        gen_tokens_total = self.get_metric_value(raw_metrics, 'vllm:generation_tokens_total')

        # Calculate rate if we have history
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

        # Total tokens
        prompt_tokens = self.get_metric_value(raw_metrics, 'vllm:prompt_tokens_total')
        metrics['prompt_tokens_total'] = int(prompt_tokens) if prompt_tokens is not None else 0

        metrics['generation_tokens_total'] = int(gen_tokens_total) if gen_tokens_total is not None else 0

        # Latency percentiles (approximated from histogram buckets)
        metrics['e2e_request_latency_p90'] = self._estimate_percentile(
            raw_metrics, 'vllm:e2e_request_latency_seconds', 0.9
        )

        metrics['time_to_first_token_p90'] = self._estimate_percentile(
            raw_metrics, 'vllm:time_to_first_token_seconds', 0.9
        )

        # Token distribution percentiles
        metrics['prompt_tokens_p50'] = self._estimate_percentile(
            raw_metrics, 'vllm:request_prompt_tokens', 0.5
        )
        metrics['prompt_tokens_p90'] = self._estimate_percentile(
            raw_metrics, 'vllm:request_prompt_tokens', 0.9
        )
        metrics['prompt_tokens_p99'] = self._estimate_percentile(
            raw_metrics, 'vllm:request_prompt_tokens', 0.99
        )

        metrics['generation_tokens_p50'] = self._estimate_percentile(
            raw_metrics, 'vllm:request_generation_tokens', 0.5
        )
        metrics['generation_tokens_p90'] = self._estimate_percentile(
            raw_metrics, 'vllm:request_generation_tokens', 0.9
        )
        metrics['generation_tokens_p99'] = self._estimate_percentile(
            raw_metrics, 'vllm:request_generation_tokens', 0.99
        )

        # Success/failure rates
        success_total = self.get_metric_value(raw_metrics, 'vllm:request_success_total')
        failure_total = self.get_metric_value(raw_metrics, 'vllm:request_failure_total')

        if success_total is not None and success_total > 0:
            total = success_total + (failure_total if failure_total else 0)
            metrics['request_success_rate'] = round((success_total / total) * 100, 1) if total > 0 else 100.0
            metrics['request_failure_rate'] = round((failure_total / total) * 100, 1) if failure_total and total > 0 else 0.0
        else:
            metrics['request_success_rate'] = 100.0
            metrics['request_failure_rate'] = 0.0

        # RPS (approximated)
        metrics['requests_per_second'] = 0.0  # Would need history to calculate

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
            if key not in ['namespace', 'model_name', 'replica_count', 'gpu_type']:
                if key not in self.history:
                    self.history[key] = []
                self.history[key].append(value)

        # Keep only last 15 data points
        if len(self.timestamps) > 15:
            self.timestamps = self.timestamps[-15:]
            for key in self.history:
                self.history[key] = self.history[key][-15:]

        return metrics

    def _estimate_percentile(self, raw_metrics, metric_prefix, percentile):
        """Estimate percentile from histogram buckets"""
        bucket_metric = f"{metric_prefix}_bucket"
        count_metric = f"{metric_prefix}_count"

        if bucket_metric not in raw_metrics:
            return 0.0

        # Get total count
        total_count = 0
        if count_metric in raw_metrics:
            total_count = self.get_metric_value(raw_metrics, count_metric)

        if not total_count or total_count == 0:
            return 0.0

        # Find the bucket containing the percentile
        target_count = total_count * percentile
        buckets = raw_metrics[bucket_metric]

        # Sort buckets by 'le' (less than or equal) value
        sorted_buckets = sorted(
            [b for b in buckets if 'le' in b['labels']],
            key=lambda x: float(x['labels']['le']) if x['labels']['le'] != '+Inf' else float('inf')
        )

        for bucket in sorted_buckets:
            if bucket['value'] >= target_count:
                le_value = bucket['labels']['le']
                if le_value == '+Inf':
                    return float('inf')
                return round(float(le_value), 2)

        return 0.0

    def _empty_metrics(self, namespace):
        """Return empty metrics structure"""
        return {
            'namespace': namespace,
            'model_name': 'unknown',
            'gpu_type': 'Unknown',
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

    def is_available(self):
        """Check if vLLM metrics endpoint is reachable"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=2)
            return response.status_code == 200
        except:
            return False
