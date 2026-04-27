#!/bin/bash

# AI Observability Dashboard - Setup Verification Script
# Tests all components to ensure dashboard can connect to live ROSA cluster

set -e

echo "=========================================="
echo "AI Observability Dashboard - Verification"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0

# Helper function
check_status() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} $1"
    else
        echo -e "${RED}✗${NC} $1"
        ERRORS=$((ERRORS + 1))
    fi
}

# Test 1: Python version
echo "1. Checking Python version..."
python3 --version > /dev/null 2>&1
check_status "Python 3.x installed"

# Test 2: Virtual environment
echo "2. Checking Python virtual environment..."
if [ -d "venv" ]; then
    echo -e "${GREEN}✓${NC} Virtual environment exists"
else
    echo -e "${YELLOW}⚠${NC} Virtual environment not found - run: python3 -m venv venv"
fi

# Test 3: Dependencies
echo "3. Checking Python dependencies..."
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    python -c "import streamlit" > /dev/null 2>&1
    check_status "Streamlit installed"

    python -c "import plotly" > /dev/null 2>&1
    check_status "Plotly installed"

    python -c "import pandas" > /dev/null 2>&1
    check_status "Pandas installed"

    python -c "import requests" > /dev/null 2>&1
    check_status "Requests installed"
else
    echo -e "${YELLOW}⚠${NC} Activate virtual environment first: source venv/bin/activate"
fi

# Test 4: OpenShift CLI
echo "4. Checking OpenShift CLI..."
oc version > /dev/null 2>&1
check_status "OpenShift CLI (oc) installed"

# Test 5: OpenShift login
echo "5. Checking OpenShift connection..."
OC_USER=$(oc whoami 2>/dev/null)
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Logged in to OpenShift as: $OC_USER"
else
    echo -e "${RED}✗${NC} Not logged in to OpenShift - run: oc login <cluster-url>"
    ERRORS=$((ERRORS + 1))
fi

# Test 6: vLLM pod exists
echo "6. Checking for vLLM pods..."
VLLM_PODS=$(oc get pods -A 2>/dev/null | grep vllm | wc -l)
if [ $VLLM_PODS -gt 0 ]; then
    echo -e "${GREEN}✓${NC} Found $VLLM_PODS vLLM pod(s)"
    oc get pods -A | grep vllm | head -3
else
    echo -e "${RED}✗${NC} No vLLM pods found in cluster"
    ERRORS=$((ERRORS + 1))
fi

# Test 7: Port-forward to vLLM
echo "7. Checking vLLM metrics endpoint..."
curl -s http://localhost:8080/health > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Port-forward to vLLM active (port 8080)"
else
    echo -e "${YELLOW}⚠${NC} Port-forward not active - run: oc port-forward -n <namespace> pod/<pod-name> 8080:8080 &"
fi

# Test 8: vLLM metrics available
echo "8. Checking vLLM Prometheus metrics..."
METRICS=$(curl -s http://localhost:8080/metrics 2>/dev/null | grep "vllm:num_requests_running" | head -1)
if [ ! -z "$METRICS" ]; then
    echo -e "${GREEN}✓${NC} vLLM metrics available"
    echo "   $METRICS"
else
    echo -e "${YELLOW}⚠${NC} vLLM metrics not accessible"
fi

# Test 9: Ollama service
echo "9. Checking Ollama AI service..."
curl -s http://localhost:11434/api/tags > /dev/null 2>&1
check_status "Ollama service running (port 11434)"

# Test 10: Granite model
echo "10. Checking Granite 3 Dense 8B model..."
GRANITE=$(curl -s http://localhost:11434/api/tags 2>/dev/null | grep "granite3-dense" | wc -l)
if [ $GRANITE -gt 0 ]; then
    echo -e "${GREEN}✓${NC} Granite 3 Dense 8B model available"
else
    echo -e "${YELLOW}⚠${NC} Granite model not found - run: ollama pull granite3-dense:8b"
fi

# Test 11: Model Serving Dashboard
echo "11. Checking Model Serving Dashboard..."
curl -s http://localhost:8501 > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Model Serving Dashboard running (port 8501)"
else
    echo -e "${YELLOW}⚠${NC} Dashboard not running - run: streamlit run app.py --server.port 8501"
fi

# Test 12: Cluster Dashboard
echo "12. Checking Cluster Dashboard..."
curl -s http://localhost:8502 > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Cluster Dashboard running (port 8502)"
else
    echo -e "${YELLOW}⚠${NC} Dashboard not running - run: streamlit run cluster_dashboard.py --server.port 8502"
fi

# Test 13: Core files exist
echo "13. Checking core application files..."
[ -f "app.py" ] && echo -e "${GREEN}✓${NC} app.py exists" || echo -e "${RED}✗${NC} app.py missing"
[ -f "cluster_dashboard.py" ] && echo -e "${GREEN}✓${NC} cluster_dashboard.py exists" || echo -e "${RED}✗${NC} cluster_dashboard.py missing"
[ -f "prometheus_client.py" ] && echo -e "${GREEN}✓${NC} prometheus_client.py exists" || echo -e "${RED}✗${NC} prometheus_client.py missing"
[ -f "bottleneck_classifier.py" ] && echo -e "${GREEN}✓${NC} bottleneck_classifier.py exists" || echo -e "${RED}✗${NC} bottleneck_classifier.py missing"
[ -f "prompts_v2.py" ] && echo -e "${GREEN}✓${NC} prompts_v2.py exists" || echo -e "${RED}✗${NC} prompts_v2.py missing"

echo ""
echo "=========================================="
echo "Verification Summary"
echo "=========================================="

if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✓ All critical checks passed!${NC}"
    echo ""
    echo "Your system is ready. Access dashboards at:"
    echo "  Model Serving: http://localhost:8501"
    echo "  Cluster View:  http://localhost:8502"
else
    echo -e "${RED}✗ Found $ERRORS issue(s)${NC}"
    echo ""
    echo "Please fix the issues above and run this script again."
    echo "See QUICKSTART.md for detailed setup instructions."
fi

echo ""
