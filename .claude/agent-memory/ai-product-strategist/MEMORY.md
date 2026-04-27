# AI Product Strategist Memory

## Project: AI Observability Dashboard for vLLM

### Core Product Insights

**Unique Value Proposition (Defensible)**:
- Hybrid AI approach: Python rules (0% hallucination) + LLM predictions (trend forecasting)
- Actionable commands validated against cluster state (builds trust)
- Deep vLLM domain expertise (KV cache vs GPU compute, decode-bound detection)

**Critical UX Gaps (Blocking Adoption)**:
- Setup requires 5+ manual steps (~15 min time-to-value)
- Port-forward dependency creates silent failures
- "Unknown GPU", "No services", "0 tok/s" create perception of broken product
- Service discovery requires manual button click (should auto-run)

**What's Working Well**:
- Hybrid AI classification (bottleneck_classifier.py) is genuinely innovative
- Generated `oc scale` commands with validation + cooldown logic
- Historical data persistence + feedback loops (thumbs up/down)
- Visual design (Perses-style, color-coded severity)

### User Segments

**Primary**: Platform engineers monitoring production vLLM
**Secondary**: ML engineers optimizing model performance
**Tertiary**: On-call teams troubleshooting incidents

**Adoption Criteria**: Setup must take <5 minutes, auto-detect services, AI accuracy >90%

### Competitive Analysis

**vs. Datadog/New Relic**: They auto-discover → we need this too
**vs. Prometheus/Grafana**: They're manual setup → we can be better with wizard
**Unique Advantage**: Hybrid AI + validated commands (no one else has this)

### Key Files

- `/app.py` - Main model serving dashboard (1623 lines)
- `/cluster_dashboard.py` - Cluster-wide monitoring (431 lines)
- `/bottleneck_classifier.py` - Python rules for 8 bottleneck types
- `/vllm_metrics_scraper.py` - Direct vLLM /metrics parsing (no Prometheus)
- `/prometheus_client.py` - Alternative Prometheus integration
- `/cluster_client.py` - OpenShift cluster validation via `oc` CLI

### Decisions Made

**Why**: Setup friction is #1 adoption blocker (affects 100% of new users)
**How to apply**: Prioritize auto-detection, connection health, setup wizard before new features

**Why**: Hybrid AI is defensible moat, not metrics charts
**How to apply**: Emphasize AI recommendations in marketing, minimize chart complexity

See: [ux_assessment_20260427.md](ux_assessment_20260427.md) for full analysis

### Success Metrics to Track

- Time to First Value: Currently ~15min → Target <3min
- Setup Success Rate: Unknown → Target >90%
- AI Insight Accuracy: Track via thumbs up/down feedback
- Command Execution Rate: Are users running generated commands?
- NPS Proxy: "Would you recommend this to your team?"

### Open Questions

1. What's the FIRST thing users try after opening dashboard?
2. Do users trust generated `oc` commands enough to run them?
3. What would make this recommended to colleagues?

### Next Steps

**Week 1** (P0 - Fix Perception):
- Add connection health indicator (port-forward status)
- Fix "Unknown GPU" messaging (show inference method)
- Better zero-state handling (throughput, services)
- Auto-discover services on page load

**Week 2** (P1 - Reduce Friction):
- Create `./start-dashboard.sh` launcher script
- Add first-time setup wizard
- Progressive disclosure for advanced features

**Week 3-4** (P2 - Validate):
- User testing with 10 platform engineers
- Measure time-to-value and setup success rate
- Iterate based on feedback
