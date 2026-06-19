# CLAUDE.md

## Harness: Deep Research

**Goal:** Investigate any topic from three independent angles (web, academic,
community), cross-validate the findings, and produce a comprehensive, cited report
with calibrated confidence.

**Trigger:** For any request to deep-research / investigate / thoroughly research a
topic, produce a comprehensive report, or assess the evidence/consensus/sentiment on
something — use the `deep-research` orchestrator skill. It fans out to the
`web-researcher`, `academic-researcher`, and `community-analyst` agents (parallel),
then `cross-validator`, then `report-writer`. Simple one-off lookups can be answered
directly without the harness.

**Execution mode:** sub-agent (Agent tool, parallel via `run_in_background`); agents
coordinate through files in `_workspace/deep-research/<slug>/`. All agents use
`model: "opus"`.

**Change log:**
| Date | Change | Target | Reason |
|------|--------|--------|--------|
| 2026-06-18 | Initial build (5 agents, 6 skills) | whole harness | — |
