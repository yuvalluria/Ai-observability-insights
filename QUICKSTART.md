# Quick Start - 5 Minutes to Live Dashboards

This guide walks through getting the AI Observability Dashboard running locally with live vLLM metrics from a ROSA cluster.

---

## Prerequisites

- Python 3.9+
- OpenShift CLI (`oc`) installed
- Access credentials to ROSA cluster
- 10 minutes of time

---

## Step 1: Clone Repository

```bash
git clone https://github.com/yuvalluria/Ai-observability-insights.git
cd Ai-observability-insights
```

---

## Step 2: Setup Python Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # macOS/Linux
# OR: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

**Expected output:** Successfully installed streamlit, pandas, plotly, requests, etc.

---

## Step 3: Setup Ollama AI (Local)

```bash
# Install Ollama (macOS)
brew install ollama

# Start Ollama service
ollama serve &

# Pull Granite 3 Dense 8B model (one-time, ~5GB download)
ollama pull granite3-dense:8b
```

**Verify Ollama is ready:**
```bash
curl http://localhost:11434/api/tags
# Should return JSON with "granite3-dense:8b" in the list
```

---

## Step 4: Connect to ROSA Cluster

```bash
# Login to your ROSA cluster
oc login <your-cluster-url> --token=<your-token>

# Verify login
oc whoami
# Should show your username

# Find vLLM pods
oc get pods -A | grep vllm
# Note the namespace and pod name
```

**Example output:**
```
lightspeed-poc    vllm-llama-model-predictor-77cbc689f4-dkngt    2/2  Running
```

---

## Step 5: Port-Forward to vLLM Service

```bash
# Set your namespace (adjust based on Step 4)
export NAMESPACE=lightspeed-poc

# Get pod name
export POD_NAME=$(oc get pods -n $NAMESPACE -l app=vllm -o jsonpath='{.items[0].metadata.name}')

# Port-forward to metrics endpoint
oc port-forward -n $NAMESPACE pod/$POD_NAME 8080:8080 &

# Verify connection
curl http://localhost:8080/metrics | grep vllm:num_requests
```

**Expected output:**
```
vllm:num_requests_running{...} 15.0
vllm:num_requests_waiting{...} 0.0
```

If you see vLLM metrics, you're connected!

---

## Step 6: Launch Dashboards

**Terminal 1 - Model Serving Dashboard:**
```bash
source venv/bin/activate
streamlit run app.py --server.port 8501
```

**Terminal 2 - Cluster Dashboard:**
```bash
source venv/bin/activate
streamlit run cluster_dashboard.py --server.port 8502
```

**Expected output:**
```
You can now view your Streamlit app in your browser.
Local URL: http://localhost:8501
```

---

## Step 7: Open Dashboards in Browser

- **Model Serving Dashboard:** http://localhost:8501
- **Cluster Dashboard:** http://localhost:8502

**What you should see:**

### Model Serving Dashboard (8501):
- Live metrics updating every 10 seconds
- GPU utilization chart
- KV cache usage chart
- Request latency (P50/P90/P99)
- AI-powered insights banner (green/yellow/red based on health)
- Chat interface for questions

### Cluster Dashboard (8502):
- Cluster overview (total models, GPUs, throughput)
- Resource usage by namespace
- AI cluster-level insights

---

## Verification Checklist

Run through this checklist to verify everything works:

### Backend Connectivity
- [ ] `oc whoami` shows logged-in user
- [ ] `curl http://localhost:8080/metrics` returns vLLM metrics
- [ ] `curl http://localhost:11434/api/tags` shows granite3-dense:8b

### Dashboard Functionality
- [ ] Model Serving Dashboard (8501) loads in browser
- [ ] Cluster Dashboard (8502) loads in browser
- [ ] Metrics charts show live data (numbers updating)
- [ ] AI insight banner appears at top of Model Serving Dashboard
- [ ] Chat interface responds to questions

### Live Metrics Validation
- [ ] GPU utilization shows percentage (e.g., 12%)
- [ ] Requests running shows number (e.g., 15)
- [ ] Requests waiting shows 0 or small number
- [ ] Latency P90 shows value in seconds
- [ ] Throughput shows tokens/sec

### AI Insights Working
- [ ] AI insight banner shows severity (INFO/WARNING/CRITICAL)
- [ ] Recommendations section shows actionable steps
- [ ] Chat responds to "Why is GPU low?" or similar questions
- [ ] Predictions section shows trend forecasts

---

## Troubleshooting

### No metrics showing in dashboard

**Check port-forward:**
```bash
curl http://localhost:8080/health
```

If fails, restart port-forward:
```bash
pkill -f "port-forward"
oc port-forward -n $NAMESPACE pod/$POD_NAME 8080:8080 &
```

### AI insights not appearing

**Check Ollama:**
```bash
ollama list
```

Should show `granite3-dense:8b`. If not:
```bash
ollama pull granite3-dense:8b
```

**Test Ollama API:**
```bash
curl http://localhost:11434/api/generate -d '{
  "model": "granite3-dense:8b",
  "prompt": "test",
  "stream": false
}'
```

### Dashboard shows "Connecting..." forever

**Check Python dependencies:**
```bash
pip list | grep streamlit
pip list | grep plotly
```

If missing, reinstall:
```bash
pip install -r requirements.txt
```

### Permission errors on ROSA cluster

**Verify you have access to namespace:**
```bash
oc get pods -n $NAMESPACE
```

If permission denied, contact cluster admin.

---

## Quick Commands Reference

**Start Everything (One Script):**
```bash
# Activate Python environment
source venv/bin/activate

# Start Ollama (if not running)
ollama serve &

# Port-forward to vLLM
export NAMESPACE=lightspeed-poc
export POD_NAME=$(oc get pods -n $NAMESPACE -l app=vllm -o jsonpath='{.items[0].metadata.name}')
oc port-forward -n $NAMESPACE pod/$POD_NAME 8080:8080 &

# Open dashboards in browser
open http://localhost:8501 &
open http://localhost:8502 &

# Launch dashboards (run in separate terminals)
streamlit run app.py --server.port 8501
streamlit run cluster_dashboard.py --server.port 8502
```

**Stop Everything:**
```bash
# Kill streamlit dashboards
pkill -f streamlit

# Kill port-forward
pkill -f "port-forward"

# Stop Ollama
pkill -f ollama
```

---

## Expected Live Metrics Example

When working correctly, you should see metrics like:

```
Requests Running: 15-25 concurrent requests
Requests Waiting: 0-2 (no backlog)
GPU KV Cache: 10-20% (healthy headroom)
Latency P90: 5-12 seconds (for long outputs)
Throughput: 300-800 tokens/sec
Model: ibm-granite/granite-8b-code-instruct
```

**AI Insight Example:**
```
[INFO]: System operating normally with capacity headroom.

Current: 20 concurrent requests, 0 waiting, 11% GPU, 11% KV cache.
Performance: P90 latency 9.7s for 409-token outputs (42.7 tok/s per request).

✓ A10G baseline: 15-25 tok/s per request
✓ No request queue (waiting=0)
✓ 89% KV headroom
✓ Low GPU = Decode-bound with spare capacity

Action: No action needed - system is right-sized for current load
```

---

## Success Criteria

You've successfully set up the dashboard when:

1. Both dashboards load in browser
2. Metrics charts show live data updating every 10 seconds
3. AI insight banner appears with health status
4. Chat responds to questions about metrics
5. Numbers match what you see in `curl http://localhost:8080/metrics`

---

## Next Steps

- Ask AI questions in chat: "Why is latency high?"
- Try cluster dashboard to see multi-service view
- Review recommendations in AI insights
- Export metrics history for analysis

---

## Support

**Issues?** Check:
1. All prerequisites installed (Python, oc, Ollama)
2. ROSA cluster login active (`oc whoami`)
3. Port-forward working (`curl http://localhost:8080/health`)
4. Ollama running (`curl http://localhost:11434/api/tags`)

**Still stuck?** Open an issue at: https://github.com/yuvalluria/Ai-observability-insights/issues
