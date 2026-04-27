import subprocess
import json
import time
import logging
from typing import Optional, Dict, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OpenShiftClusterClient:
    """
    Query OpenShift cluster for deployment information to validate generated commands.
    Uses subprocess to call oc CLI - reliable and simple approach.
    """

    def __init__(self, oc_path: str = "/opt/homebrew/bin/oc"):
        """
        Initialize OpenShift cluster client.

        Args:
            oc_path: Path to oc CLI binary
        """
        self.oc_path = oc_path
        self.cache = {}
        self.cache_ttl = 30  # 30-second cache TTL

    def _get_cached_or_query(self, cache_key: str, query_func: callable) -> Any:
        """
        Generic cache wrapper to avoid excessive oc CLI calls.

        Args:
            cache_key: Unique key for this query
            query_func: Function to call if cache miss

        Returns:
            Cached or fresh query result
        """
        if cache_key in self.cache:
            cached_time, cached_value = self.cache[cache_key]
            if time.time() - cached_time < self.cache_ttl:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_value

        # Cache miss - execute query
        result = query_func()
        self.cache[cache_key] = (time.time(), result)
        return result

    def is_logged_in(self) -> bool:
        """
        Check if oc is logged into a cluster.

        Returns:
            True if logged in, False otherwise
        """
        def _check_login():
            try:
                result = subprocess.run(
                    [self.oc_path, 'whoami'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True
                )
                return result.returncode == 0 and result.stdout.strip() != ""
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
                logger.debug(f"Not logged in to OpenShift: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected error checking login: {e}")
                return False

        return self._get_cached_or_query("is_logged_in", _check_login)

    def get_current_context(self) -> Optional[Dict[str, str]]:
        """
        Get current cluster/project context.

        Returns:
            Dict with 'context' and 'namespace', or None on failure
        """
        def _get_context():
            try:
                # Get current project/namespace
                result = subprocess.run(
                    [self.oc_path, 'project', '-q'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True
                )

                namespace = result.stdout.strip()

                return {
                    'namespace': namespace,
                    'context': 'openshift'
                }
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                logger.debug(f"Could not get current context: {e}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error getting context: {e}")
                return None

        return self._get_cached_or_query("current_context", _get_context)

    def _extract_resources(self, deployment_data: Dict) -> Dict[str, str]:
        """
        Extract resource limits from deployment JSON.

        Args:
            deployment_data: Deployment JSON from oc get deployment

        Returns:
            Dict with 'memory' and 'gpu' resource limits
        """
        try:
            containers = deployment_data.get('spec', {}).get('template', {}).get('spec', {}).get('containers', [])
            if not containers:
                return {'memory': 'unknown', 'gpu': 'unknown'}

            # Get limits from first container
            limits = containers[0].get('resources', {}).get('limits', {})

            return {
                'memory': limits.get('memory', 'unknown'),
                'gpu': limits.get('nvidia.com/gpu', 'unknown')
            }
        except Exception as e:
            logger.warning(f"Could not extract resources: {e}")
            return {'memory': 'unknown', 'gpu': 'unknown'}

    def _extract_env_vars(self, deployment_data: Dict) -> Dict[str, str]:
        """
        Extract environment variables from deployment JSON.

        Args:
            deployment_data: Deployment JSON from oc get deployment

        Returns:
            Dict of environment variables
        """
        try:
            containers = deployment_data.get('spec', {}).get('template', {}).get('spec', {}).get('containers', [])
            if not containers:
                return {}

            # Get env vars from first container
            env_list = containers[0].get('env', [])

            env_vars = {}
            for env in env_list:
                name = env.get('name')
                value = env.get('value')
                if name and value:
                    env_vars[name] = value

            return env_vars
        except Exception as e:
            logger.warning(f"Could not extract env vars: {e}")
            return {}

    def get_deployment_info(self, namespace: str, deployment_name: str) -> Optional[Dict[str, Any]]:
        """
        Query deployment details from OpenShift cluster.

        Args:
            namespace: Kubernetes namespace
            deployment_name: Name of deployment to query

        Returns:
            Dict with deployment info, or None on failure:
            {
                'exists': bool,
                'name': str,
                'namespace': str,
                'replicas': int,
                'current_replicas': int,
                'resources': {'memory': str, 'gpu': str},
                'env_vars': dict
            }
        """
        cache_key = f"deployment_{namespace}_{deployment_name}"

        def _query_deployment():
            try:
                result = subprocess.run(
                    [self.oc_path, 'get', 'deployment', deployment_name,
                     '-n', namespace, '-o', 'json'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True
                )

                data = json.loads(result.stdout)

                return {
                    'exists': True,
                    'name': data['metadata']['name'],
                    'namespace': data['metadata']['namespace'],
                    'replicas': data['spec'].get('replicas', 0),
                    'current_replicas': data['status'].get('replicas', 0),
                    'resources': self._extract_resources(data),
                    'env_vars': self._extract_env_vars(data)
                }

            except subprocess.TimeoutExpired:
                logger.warning(f"Timeout querying deployment {deployment_name} in {namespace}")
                return {'exists': False, 'error': 'timeout'}

            except subprocess.CalledProcessError as e:
                if 'NotFound' in e.stderr or 'not found' in e.stderr.lower():
                    logger.info(f"Deployment {deployment_name} not found in {namespace}")
                    return {'exists': False, 'error': 'not_found'}
                logger.error(f"Error querying deployment: {e.stderr}")
                return {'exists': False, 'error': 'unknown'}

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from oc command: {e}")
                return {'exists': False, 'error': 'parse_error'}

            except FileNotFoundError:
                logger.error(f"oc CLI not found at {self.oc_path}")
                return {'exists': False, 'error': 'oc_not_found'}

            except Exception as e:
                logger.error(f"Unexpected error querying deployment: {str(e)}")
                return {'exists': False, 'error': 'unknown'}

        return self._get_cached_or_query(cache_key, _query_deployment)

    def list_deployments(self, namespace: str, label_selector: Optional[str] = None) -> list:
        """
        List deployments in namespace.

        Args:
            namespace: Kubernetes namespace
            label_selector: Optional label selector (e.g., "app=vllm")

        Returns:
            List of deployment names, or empty list on failure
        """
        try:
            cmd = [self.oc_path, 'get', 'deployments', '-n', namespace, '-o', 'json']

            if label_selector:
                cmd.extend(['-l', label_selector])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                check=True
            )

            data = json.loads(result.stdout)
            items = data.get('items', [])

            return [item['metadata']['name'] for item in items]

        except Exception as e:
            logger.error(f"Error listing deployments in {namespace}: {e}")
            return []

    def validate_namespace(self, namespace: str) -> bool:
        """
        Check if namespace exists and is accessible.

        Args:
            namespace: Kubernetes namespace to validate

        Returns:
            True if namespace exists and is accessible, False otherwise
        """
        cache_key = f"namespace_{namespace}"

        def _check_namespace():
            try:
                result = subprocess.run(
                    [self.oc_path, 'get', 'namespace', namespace],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True
                )

                return result.returncode == 0

            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                logger.debug(f"Namespace {namespace} not accessible: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected error validating namespace: {e}")
                return False

        return self._get_cached_or_query(cache_key, _check_namespace)

    def get_gpu_type_from_nodes(self) -> str:
        """
        Detect GPU type from NVIDIA GPU Operator labels on cluster nodes.

        Returns:
            GPU type string (e.g., "NVIDIA A10G (24GB)", "NVIDIA T4 (16GB)"), or "Unknown"
        """
        cache_key = "gpu_type_from_nodes"

        def _detect_gpu():
            try:
                result = subprocess.run(
                    [self.oc_path, 'get', 'nodes', '-o', 'json'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True
                )

                nodes_data = json.loads(result.stdout)

                # Find nodes with GPUs and read NVIDIA labels
                for node in nodes_data.get('items', []):
                    labels = node.get('metadata', {}).get('labels', {})

                    # Check if node has GPU
                    gpu_count = node.get('status', {}).get('capacity', {}).get('nvidia.com/gpu')
                    if not gpu_count:
                        continue

                    # Try to get GPU info from NVIDIA labels (most accurate)
                    gpu_product = labels.get('nvidia.com/gpu.product')
                    gpu_memory_mib = labels.get('nvidia.com/gpu.memory')

                    if gpu_product:
                        # Clean up product name (e.g., "NVIDIA-A10G" -> "A10G")
                        gpu_name = gpu_product.replace('NVIDIA-', '').replace('NVIDIA ', '').strip()

                        # Round memory to common spec
                        if gpu_memory_mib:
                            try:
                                memory_gb = int(gpu_memory_mib) / 1024.0
                                # Round to nearest common GPU size
                                if 14 <= memory_gb < 18:
                                    memory_display = "16GB"  # T4
                                elif 22 <= memory_gb < 26:
                                    memory_display = "24GB"  # A10G
                                elif 38 <= memory_gb < 42:
                                    memory_display = "40GB"  # A100
                                elif 78 <= memory_gb < 82:
                                    memory_display = "80GB"  # A100/H100
                                else:
                                    memory_display = f"{int(memory_gb)}GB"

                                # Also return architecture and CUDA version
                                gpu_family = labels.get('nvidia.com/gpu.family', '').title()
                                return f"NVIDIA {gpu_name} ({memory_display})"
                            except (ValueError, TypeError):
                                return f"NVIDIA {gpu_name}"
                        else:
                            return f"NVIDIA {gpu_name}"

                    # Fallback: Map instance type if NVIDIA labels not available
                    instance_type = labels.get('node.kubernetes.io/instance-type', '')
                    if 'g5' in instance_type.lower():
                        return "NVIDIA A10G (24GB)"
                    elif 'g4dn' in instance_type.lower():
                        return "NVIDIA T4 (16GB)"
                    elif 'p4d' in instance_type.lower():
                        return "NVIDIA A100 (40GB)"
                    elif 'p5' in instance_type.lower():
                        return "NVIDIA H100 (80GB)"
                    elif instance_type:
                        return f"GPU ({instance_type})"

                return "Unknown"

            except Exception as e:
                logger.debug(f"Could not detect GPU from nodes: {e}")
                return "Unknown"

        return self._get_cached_or_query(cache_key, _detect_gpu)

    def get_gpu_metadata(self) -> Dict[str, str]:
        """
        Get detailed GPU metadata including architecture, CUDA version, compute capability.

        Returns:
            Dict with keys: architecture, cuda_version, compute_capability
        """
        cache_key = "gpu_metadata"

        def _get_metadata():
            try:
                result = subprocess.run(
                    [self.oc_path, 'get', 'nodes', '-o', 'json'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True
                )

                nodes_data = json.loads(result.stdout)

                # Find nodes with GPUs
                for node in nodes_data.get('items', []):
                    labels = node.get('metadata', {}).get('labels', {})

                    gpu_count = node.get('status', {}).get('capacity', {}).get('nvidia.com/gpu')
                    if not gpu_count:
                        continue

                    # Extract metadata
                    architecture = labels.get('nvidia.com/gpu.family', 'Unknown').title()
                    cuda_version = labels.get('nvidia.com/cuda.runtime-version.full', 'Unknown')
                    compute_major = labels.get('nvidia.com/gpu.compute.major', '')
                    compute_minor = labels.get('nvidia.com/gpu.compute.minor', '')

                    compute_capability = f"{compute_major}.{compute_minor}" if compute_major and compute_minor else "Unknown"

                    return {
                        'architecture': architecture,
                        'cuda_version': cuda_version,
                        'compute_capability': compute_capability
                    }

                return {
                    'architecture': 'Unknown',
                    'cuda_version': 'Unknown',
                    'compute_capability': 'Unknown'
                }

            except Exception as e:
                logger.debug(f"Could not get GPU metadata: {e}")
                return {
                    'architecture': 'Unknown',
                    'cuda_version': 'Unknown',
                    'compute_capability': 'Unknown'
                }

        return self._get_cached_or_query(cache_key, _get_metadata)

    def list_namespaces(self) -> list:
        """
        List all namespaces in the cluster.

        Returns:
            List of namespace names, or empty list on failure
        """
        cache_key = "all_namespaces"

        def _list_namespaces():
            try:
                result = subprocess.run(
                    [self.oc_path, 'get', 'namespaces', '-o', 'json'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True
                )

                data = json.loads(result.stdout)
                items = data.get('items', [])

                return [item['metadata']['name'] for item in items]

            except Exception as e:
                logger.error(f"Error listing namespaces: {e}")
                return []

        return self._get_cached_or_query(cache_key, _list_namespaces)

    def discover_vllm_services(self) -> list:
        """
        Auto-discover all vLLM/KServe InferenceService deployments across cluster.

        Returns:
            List of dicts with service info:
            [
                {
                    'name': 'granite-8b',
                    'namespace': 'team-a',
                    'type': 'deployment',  # or 'inferenceservice'
                    'model': 'granite-8b-code-instruct',
                    'replicas': 2
                },
                ...
            ]
        """
        cache_key = "discovered_vllm_services"

        def _discover():
            services = []

            try:
                # Get all namespaces
                namespaces = self.list_namespaces()

                for ns in namespaces:
                    # Skip system namespaces
                    if ns.startswith(('kube-', 'openshift-', 'default')):
                        continue

                    # Look for vLLM deployments (label: serving.kserve.io/inferenceservice)
                    try:
                        result = subprocess.run(
                            [self.oc_path, 'get', 'deployments', '-n', ns,
                             '-l', 'serving.kserve.io/inferenceservice',
                             '-o', 'json'],
                            capture_output=True,
                            text=True,
                            timeout=5,
                            check=True
                        )

                        data = json.loads(result.stdout)
                        items = data.get('items', [])

                        for item in items:
                            metadata = item.get('metadata', {})
                            spec = item.get('spec', {})
                            status = item.get('status', {})

                            # Extract service info
                            service_info = {
                                'name': metadata.get('name', ''),
                                'namespace': metadata.get('namespace', ns),
                                'type': 'deployment',
                                'labels': metadata.get('labels', {}),
                                'replicas': spec.get('replicas', 0),
                                'ready_replicas': status.get('readyReplicas', 0),
                                'created': metadata.get('creationTimestamp', '')
                            }

                            # Try to extract model name from:
                            # 1. Environment variables (MODEL_NAME, HF_MODEL_ID)
                            # 2. Labels
                            # 3. Fallback to deployment name
                            model_name = 'unknown'

                            # Check env vars in containers
                            containers = spec.get('template', {}).get('spec', {}).get('containers', [])
                            for container in containers:
                                env_vars = container.get('env', [])
                                for env_var in env_vars:
                                    if env_var.get('name') in ['MODEL_NAME', 'HF_MODEL_ID', 'MODEL_ID']:
                                        model_name = env_var.get('value', 'unknown')
                                        break
                                if model_name != 'unknown':
                                    break

                            # Fallback to labels if not found in env vars
                            if model_name == 'unknown':
                                labels = metadata.get('labels', {})
                                model_name = labels.get('model', labels.get('serving.kserve.io/inferenceservice', metadata.get('name', 'unknown')))

                            service_info['model'] = model_name

                            services.append(service_info)

                    except subprocess.CalledProcessError:
                        # No vLLM deployments in this namespace
                        continue
                    except Exception as e:
                        logger.debug(f"Error discovering services in {ns}: {e}")
                        continue

                logger.info(f"Discovered {len(services)} vLLM services across cluster")
                return services

            except Exception as e:
                logger.error(f"Error during service discovery: {e}")
                return []

        return self._get_cached_or_query(cache_key, _discover)

    def get_cluster_resource_summary(self) -> Dict[str, Any]:
        """
        Get cluster-wide resource summary (total nodes, GPUs, capacity).

        Returns:
            Dict with cluster resource information
        """
        cache_key = "cluster_resources"

        def _get_resources():
            try:
                result = subprocess.run(
                    [self.oc_path, 'get', 'nodes', '-o', 'json'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True
                )

                nodes_data = json.loads(result.stdout)
                nodes = nodes_data.get('items', [])

                total_nodes = len(nodes)
                ready_nodes = 0
                total_gpus = 0
                total_cpu = 0
                total_memory = 0

                for node in nodes:
                    # Check if node is ready
                    conditions = node.get('status', {}).get('conditions', [])
                    for condition in conditions:
                        if condition.get('type') == 'Ready' and condition.get('status') == 'True':
                            ready_nodes += 1
                            break

                    # Sum capacity
                    capacity = node.get('status', {}).get('capacity', {})

                    # GPUs
                    gpu_count = capacity.get('nvidia.com/gpu', '0')
                    try:
                        total_gpus += int(gpu_count)
                    except (ValueError, TypeError):
                        pass

                    # CPU (in cores)
                    cpu_count = capacity.get('cpu', '0')
                    try:
                        total_cpu += int(cpu_count)
                    except (ValueError, TypeError):
                        pass

                    # Memory (convert from Ki to GB)
                    memory_ki = capacity.get('memory', '0Ki').replace('Ki', '')
                    try:
                        total_memory += int(memory_ki) / (1024 * 1024)  # Ki to GB
                    except (ValueError, TypeError):
                        pass

                return {
                    'total_nodes': total_nodes,
                    'ready_nodes': ready_nodes,
                    'total_gpus': total_gpus,
                    'total_cpu_cores': total_cpu,
                    'total_memory_gb': round(total_memory, 1),
                    'health_ratio': round(ready_nodes / total_nodes, 2) if total_nodes > 0 else 0
                }

            except Exception as e:
                logger.error(f"Error getting cluster resources: {e}")
                return {
                    'total_nodes': 0,
                    'ready_nodes': 0,
                    'total_gpus': 0,
                    'total_cpu_cores': 0,
                    'total_memory_gb': 0,
                    'health_ratio': 0
                }

        return self._get_cached_or_query(cache_key, _get_resources)
