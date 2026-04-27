import requests
import time
from datetime import datetime, timedelta

class PrometheusClient:
    """Client to query Prometheus for vLLM metrics"""

    def __init__(self, prometheus_url="http://localhost:9090", cluster_client=None):
        self.base_url = prometheus_url
        self.history = {}
        self.timestamps = []
        self.cluster_client = cluster_client

    def query(self, query_string):
        """Execute a PromQL query"""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/query",
                params={'query': query_string},
                timeout=5
            )
            if response.status_code == 200:
                result = response.json()
                if result['status'] == 'success' and result['data']['result']:
                    return float(result['data']['result'][0]['value'][1])
            return None
        except Exception as e:
            print(f"Prometheus query error: {e}")
            return None

    def query_range(self, query_string, start, end, step='15s'):
        """Execute a PromQL range query"""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/query_range",
                params={
                    'query': query_string,
                    'start': start,
                    'end': end,
                    'step': step
                },
                timeout=5
            )
            if response.status_code == 200:
                result = response.json()
                if result['status'] == 'success' and result['data']['result']:
                    values = result['data']['result'][0]['values']
                    return [(datetime.fromtimestamp(v[0]), float(v[1])) for v in values]
            return []
        except Exception as e:
            print(f"Prometheus range query error: {e}")
            return []

    def get_metrics(self, namespace="lightspeed-poc", service="vllm-llama-model-predictor"):
        """Fetch current vLLM metrics from Prometheus"""
        metrics = {}

        # GPU type detection (try Prometheus first, fall back to cluster)
        gpu_type = "Unknown"
        gpu_memory_bytes = self.query('vllm:gpu_config_total_memory_bytes')

        if gpu_memory_bytes is not None:
            gpu_memory_gb = gpu_memory_bytes / (1024**3)
            # Map memory to GPU type
            if 14 <= gpu_memory_gb < 20:
                gpu_type = "NVIDIA T4 (16GB)"
            elif 22 <= gpu_memory_gb < 26:
                gpu_type = "NVIDIA A10G (24GB)"
            elif 38 <= gpu_memory_gb < 50:
                gpu_type = "NVIDIA A100 (40GB)"
            elif 78 <= gpu_memory_gb < 90:
                gpu_type = "NVIDIA A100 (80GB)"
            else:
                gpu_type = f"Unknown ({gpu_memory_gb:.0f}GB)"
        elif self.cluster_client and self.cluster_client.is_logged_in():
            # Fall back to querying node instance type
            gpu_type = self.cluster_client.get_gpu_type_from_nodes()

        metrics['gpu_type'] = gpu_type

        # KV Cache utilization (0-100%) - vLLM-specific memory metric
        kv_cache = self.query('vllm:gpu_cache_usage_perc')
        metrics['kv_cache_usage_perc'] = int(kv_cache * 100) if kv_cache is not None else 0

        # GPU Compute utilization (0-100%) - from NVIDIA/DCGM metrics
        # Try multiple potential metric names (different exporters use different names)
        gpu_compute = None

        # Try DCGM exporter metric
        gpu_compute = self.query('DCGM_FI_DEV_GPU_UTIL')

        # Try nvidia-smi exporter metric if DCGM not available
        if gpu_compute is None:
            gpu_compute = self.query('nvidia_smi_utilization_gpu_ratio')

        # Try node exporter GPU metric if others not available
        if gpu_compute is None:
            gpu_compute = self.query('node_gpu_utilization')

        # If no GPU compute metric available, use KV cache as approximation with note
        if gpu_compute is not None:
            metrics['gpu_compute_utilization'] = int(gpu_compute) if gpu_compute < 1 else int(gpu_compute)
        else:
            # Fallback: use KV cache as proxy (not ideal but better than nothing)
            metrics['gpu_compute_utilization'] = metrics['kv_cache_usage_perc']

        # Legacy field for backwards compatibility (use KV cache)
        metrics['gpu_utilization'] = metrics['kv_cache_usage_perc']

        # Running requests
        running = self.query('vllm:num_requests_running')
        metrics['num_requests_running'] = int(running) if running is not None else 0

        # Waiting requests
        waiting = self.query('vllm:num_requests_waiting')
        metrics['num_requests_waiting'] = int(waiting) if waiting is not None else 0

        # E2E latency P90 (convert from milliseconds to seconds)
        latency = self.query('histogram_quantile(0.9, rate(vllm:e2e_request_latency_seconds_bucket[5m]))')
        metrics['e2e_request_latency_p90'] = round(latency, 2) if latency is not None else 0.0

        # Time to first token P90
        ttft = self.query('histogram_quantile(0.9, rate(vllm:time_to_first_token_seconds_bucket[5m]))')
        metrics['time_to_first_token_p90'] = round(ttft, 2) if ttft is not None else 0.0

        # Tokens per second (output throughput)
        tps = self.query('rate(vllm:generation_tokens_total[1m])')
        metrics['tokens_per_second'] = int(tps) if tps is not None else 0

        # Requests per second
        rps = self.query('rate(vllm:request_success_total[1m])')
        metrics['requests_per_second'] = round(rps, 1) if rps is not None else 0.0

        # Success/failure rates
        success_total = self.query('sum(vllm:request_success_total)')
        failure_total = self.query('sum(vllm:request_failure_total)')

        if success_total is not None and success_total > 0:
            metrics['request_success_rate'] = 100.0
            metrics['request_failure_rate'] = 0.0
        else:
            metrics['request_success_rate'] = 100.0
            metrics['request_failure_rate'] = 0.0

        # CPU utilization - set to 0 for now (container metrics not available from Docker Prometheus)
        metrics['cpu_utilization_pct'] = 0

        # Token counts
        prompt_tokens = self.query('vllm:prompt_tokens_total')
        metrics['prompt_tokens_total'] = int(prompt_tokens) if prompt_tokens is not None else 0

        generation_tokens = self.query('vllm:generation_tokens_total')
        metrics['generation_tokens_total'] = int(generation_tokens) if generation_tokens is not None else 0

        # Token distribution percentiles (input)
        prompt_p50 = self.query('histogram_quantile(0.5, rate(vllm:request_prompt_tokens_bucket[5m]))')
        metrics['prompt_tokens_p50'] = int(prompt_p50) if prompt_p50 is not None else 0

        prompt_p90 = self.query('histogram_quantile(0.9, rate(vllm:request_prompt_tokens_bucket[5m]))')
        metrics['prompt_tokens_p90'] = int(prompt_p90) if prompt_p90 is not None else 0

        prompt_p99 = self.query('histogram_quantile(0.99, rate(vllm:request_prompt_tokens_bucket[5m]))')
        metrics['prompt_tokens_p99'] = int(prompt_p99) if prompt_p99 is not None else 0

        # Token distribution percentiles (output)
        gen_p50 = self.query('histogram_quantile(0.5, rate(vllm:request_generation_tokens_bucket[5m]))')
        metrics['generation_tokens_p50'] = int(gen_p50) if gen_p50 is not None else 0

        gen_p90 = self.query('histogram_quantile(0.9, rate(vllm:request_generation_tokens_bucket[5m]))')
        metrics['generation_tokens_p90'] = int(gen_p90) if gen_p90 is not None else 0

        gen_p99 = self.query('histogram_quantile(0.99, rate(vllm:request_generation_tokens_bucket[5m]))')
        metrics['generation_tokens_p99'] = int(gen_p99) if gen_p99 is not None else 0

        # Batch size configuration (from cluster if available)
        batch_size = None  # None = not explicitly configured
        max_seqs = None
        if self.cluster_client and self.cluster_client.is_logged_in():
            deployment_info = self.cluster_client.get_deployment_info(namespace, service)
            if deployment_info and deployment_info.get('exists'):
                env_vars = deployment_info.get('env_vars', {})
                # Common vLLM batch size env vars
                if 'MAX_NUM_BATCHED_TOKENS' in env_vars:
                    batch_size = env_vars['MAX_NUM_BATCHED_TOKENS']
                elif 'MAX_BATCH_SIZE' in env_vars:
                    batch_size = env_vars['MAX_BATCH_SIZE']

                if 'MAX_NUM_SEQS' in env_vars:
                    max_seqs = env_vars['MAX_NUM_SEQS']

        metrics['batch_size'] = batch_size
        metrics['max_num_seqs'] = max_seqs

        # Replica count (from running pods)
        replica_count = self.query(f'count(kserve_vllm:num_requests_running{{namespace="{namespace}"}})')
        if replica_count is None:
            # Fallback: try vllm metrics without kserve prefix
            replica_count = self.query(f'count(vllm:num_requests_running{{namespace="{namespace}"}})')
        metrics['replica_count'] = int(replica_count) if replica_count is not None else 1

        # GPU metadata (architecture, CUDA version)
        if self.cluster_client:
            gpu_metadata = self.cluster_client.get_gpu_metadata()
            metrics['gpu_architecture'] = gpu_metadata.get('architecture', 'Unknown')
            metrics['cuda_version'] = gpu_metadata.get('cuda_version', 'Unknown')
            metrics['compute_capability'] = gpu_metadata.get('compute_capability', 'Unknown')
        else:
            metrics['gpu_architecture'] = 'Unknown'
            metrics['cuda_version'] = 'Unknown'
            metrics['compute_capability'] = 'Unknown'

        # Extract model name from Prometheus metric labels (if available)
        model_name = 'unknown'
        try:
            # Query vLLM metric to extract model_name label
            response = requests.get(
                f"{self.base_url}/api/v1/query",
                params={'query': f'vllm:num_requests_running{{namespace="{namespace}"}}'},
                timeout=5
            )
            if response.status_code == 200:
                result = response.json()
                if result['status'] == 'success' and result['data']['result']:
                    # Extract model_name from metric labels
                    metric_labels = result['data']['result'][0].get('metric', {})
                    model_name = metric_labels.get('model_name', metric_labels.get('model', 'granite-8b-code-instruct'))
        except:
            model_name = 'granite-8b-code-instruct'  # Fallback

        metrics['namespace'] = namespace
        metrics['model_name'] = model_name

        # Update history
        self.timestamps.append(datetime.now().strftime("%H:%M:%S"))
        for key, value in metrics.items():
            if key not in ['namespace', 'model_name', 'replica_count']:
                if key not in self.history:
                    self.history[key] = []
                self.history[key].append(value)

        # Keep only last 15 data points
        if len(self.timestamps) > 15:
            self.timestamps = self.timestamps[-15:]
            for key in self.history:
                self.history[key] = self.history[key][-15:]

        return metrics

    def is_available(self):
        """Check if Prometheus is reachable"""
        try:
            response = requests.get(f"{self.base_url}/api/v1/status/config", timeout=2)
            return response.status_code == 200
        except:
            return False

    def get_cluster_metrics(self):
        """
        Get cluster-wide aggregated metrics across all vLLM services.

        Returns:
            Dict with cluster-wide metrics
        """
        metrics = {}

        # Count total unique models across all namespaces
        model_count_query = 'count(count by (model_name, namespace) (vllm:num_requests_running))'
        model_count = self.query(model_count_query)
        metrics['total_models'] = int(model_count) if model_count is not None else 0

        # Average GPU utilization across cluster
        avg_gpu_query = 'avg(vllm:gpu_cache_usage_perc) * 100'
        avg_gpu = self.query(avg_gpu_query)
        metrics['avg_gpu_utilization'] = int(avg_gpu) if avg_gpu is not None else 0

        # Total cluster throughput (tokens/sec across all services)
        cluster_throughput_query = 'sum(rate(vllm:generation_tokens_total[1m]))'
        throughput = self.query(cluster_throughput_query)
        metrics['cluster_throughput'] = int(throughput) if throughput is not None else 0

        # Cluster-wide success rate
        success_query = 'sum(rate(vllm:request_success_total[1m]))'
        failure_query = 'sum(rate(vllm:request_failure_total[1m]))'

        success_rate = self.query(success_query)
        failure_rate = self.query(failure_query)

        if success_rate is not None and success_rate > 0:
            total_requests = success_rate + (failure_rate if failure_rate is not None else 0)
            metrics['cluster_success_rate'] = round((success_rate / total_requests) * 100, 1) if total_requests > 0 else 100.0
        else:
            metrics['cluster_success_rate'] = 100.0

        # Total requests running/waiting across cluster
        running_query = 'sum(vllm:num_requests_running)'
        waiting_query = 'sum(vllm:num_requests_waiting)'

        running = self.query(running_query)
        waiting = self.query(waiting_query)

        metrics['total_requests_running'] = int(running) if running is not None else 0
        metrics['total_requests_waiting'] = int(waiting) if waiting is not None else 0

        # Average latency across cluster
        avg_latency_query = 'avg(histogram_quantile(0.9, rate(vllm:e2e_request_latency_seconds_bucket[5m])))'
        avg_latency = self.query(avg_latency_query)
        metrics['avg_latency_p90'] = round(avg_latency, 2) if avg_latency is not None else 0.0

        return metrics

    def get_metrics_by_namespace(self):
        """
        Get resource usage broken down by namespace.

        Returns:
            List of dicts with per-namespace metrics
        """
        namespaces_data = []

        try:
            # Query for GPU usage by namespace
            gpu_query = 'avg by (namespace) (vllm:gpu_cache_usage_perc) * 100'
            response = requests.get(
                f"{self.base_url}/api/v1/query",
                params={'query': gpu_query},
                timeout=5
            )

            if response.status_code == 200:
                result = response.json()
                if result['status'] == 'success':
                    for item in result['data']['result']:
                        namespace = item['metric'].get('namespace', 'unknown')
                        gpu_util = float(item['value'][1])

                        namespaces_data.append({
                            'namespace': namespace,
                            'gpu_utilization': int(gpu_util)
                        })

            # Enrich with throughput per namespace
            throughput_query = 'sum by (namespace) (rate(vllm:generation_tokens_total[1m]))'
            response = requests.get(
                f"{self.base_url}/api/v1/query",
                params={'query': throughput_query},
                timeout=5
            )

            if response.status_code == 200:
                result = response.json()
                if result['status'] == 'success':
                    for item in result['data']['result']:
                        namespace = item['metric'].get('namespace', 'unknown')
                        throughput = float(item['value'][1])

                        # Find matching namespace in data
                        for ns_data in namespaces_data:
                            if ns_data['namespace'] == namespace:
                                ns_data['throughput'] = int(throughput)
                                break
                        else:
                            # Namespace not in GPU data, add it
                            namespaces_data.append({
                                'namespace': namespace,
                                'gpu_utilization': 0,
                                'throughput': int(throughput)
                            })

            return namespaces_data

        except Exception as e:
            print(f"Error getting namespace metrics: {e}")
            return []

    def get_all_services_metrics(self):
        """
        Get metrics for each individual vLLM service/deployment.

        Returns:
            List of dicts with per-service metrics
        """
        services_data = []

        try:
            # Query for metrics grouped by model and namespace
            query = '''
            vllm:num_requests_running
            '''

            response = requests.get(
                f"{self.base_url}/api/v1/query",
                params={'query': query},
                timeout=5
            )

            if response.status_code == 200:
                result = response.json()
                if result['status'] == 'success':
                    for item in result['data']['result']:
                        metric_labels = item['metric']

                        service_name = metric_labels.get('model_name', 'unknown')
                        namespace = metric_labels.get('namespace', 'unknown')

                        # Get all metrics for this service
                        service_metrics = self.get_metrics(namespace=namespace, service=service_name)
                        service_metrics['service_name'] = service_name
                        service_metrics['namespace'] = namespace

                        services_data.append(service_metrics)

            return services_data

        except Exception as e:
            print(f"Error getting all services metrics: {e}")
            return []
