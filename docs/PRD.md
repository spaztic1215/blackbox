# Blackbox: Product Requirements Document (PRD)

## Overview

- **Product Name:** Blackbox
- **Tagline:** AI-powered investigation for third-party integrations
- **Version:** 0.1 (MVP/Prototype)
- **Status:** Pre-development
- **Target Completion:** 2 weeks from start

## Problem Statement

Modern production systems integrate black-box third-party services (fraud detection APIs, content moderation, credit scoring, etc.) that make critical decisions. When anomalies appear downstream—often days or weeks later—investigation is painfully manual:

- **Scattered data:** Inputs/outputs/decisions spread across logs, databases, message queues
- **No audit trail:** Can't reconstruct "what exactly happened and why?"
- **Version chaos:** Gradual rollouts (feature flags, canaries, A/B tests) make attribution nearly impossible
- **Slow investigations:** Takes 2-5 days of manual SQL queries and spreadsheet analysis to answer "why did X spike?"

**Example scenario:** E-commerce company rolls out fraud model v2.4.1 gradually (10% → 50% → 100% of users over 3 days). On day 2, fraud decline rate spikes from 8% to 12%. Investigation currently requires:

1. Querying application logs across multiple systems
2. Joining tables to correlate users, fraud scores, and decisions
3. Building spreadsheets to compare cohorts
4. Manual hypothesis testing to determine if it's the new model, organic growth, or data quality issue

This takes 2-3 days of analyst time and often yields incomplete answers.

## Solution

Blackbox orchestrates all third-party integrations as Temporal workflows (providing complete Event History = audit trail) + AI agents (to query/analyze/explain) to enable:

- **Instant investigation:** "Why did fraud declines spike?" → AI agent answers in 30 seconds
- **Complete auditability:** Every decision has full input/output/reasoning captured
- **Version attribution:** Isolate changes to specific model versions or user cohorts
- **Counterfactual analysis:** "What would've happened under the old version?"

## Target Users (for MVP)

**Primary:** Engineering teams using Temporal (or considering it) who integrate third-party decision-making services

**Personas:**

- **Backend Engineer** - Integrating fraud API, wants observability
- **Platform Engineer** - Rolling out model versions, needs safe deployment
- **Data Analyst** - Investigating anomalies, needs faster root cause analysis

**Not targeting (for MVP):**

- Non-technical business users
- Teams not using Temporal
- Teams without gradual rollout complexity

## User Stories

### Core User Journey (MVP Focus)

> As a **backend engineer**, I want to see complete audit trails for every third-party API call,
> So that when something goes wrong, I can trace exactly what happened.

> As a **platform engineer**, I want to understand how a gradual model rollout affects my metrics,
> So that I can decide whether to accelerate, pause, or rollback.

> As a **data analyst**, I want to ask natural language questions about workflow patterns,
> So that I can investigate anomalies 10x faster than manual SQL queries.

### Specific Use Cases

**Use Case 1: Model Version Attribution**

1. User notices fraud decline rate spike
2. User asks AI agent: "Why did fraud declines spike on Jan 16?"
3. Agent queries Temporal workflows, analyzes by model version
4. Agent responds: "Spike entirely from v2.4.1 (50% rollout). Users on v2.4.0 unaffected. New model 2.5x more sensitive to user velocity."
5. User drills into specific workflows to see examples

**Use Case 2: Cohort Analysis**

1. User suspects regional differences in fraud scoring
2. User asks: "Are we seeing different patterns by country?"
3. Agent analyzes workflows grouped by shipping country
4. Agent responds: "International orders (non-US shipping) have 3x higher decline rate on v2.4.1 vs v2.4.0"

**Use Case 3: Counterfactual Investigation**

1. User wants to validate if old model would've performed better
2. User asks: "What would these declined orders have scored under v2.4.0?"
3. Agent replays workflow logic (or simulates based on captured inputs)
4. Agent shows side-by-side comparison

**Use Case 4: Remediation Planning**

1. User determines new model is over-aggressive
2. User asks: "Which workflows should I reprocess?"
3. Agent identifies affected workflows and generates batch command
4. User executes remediation via Temporal batch operations

## MVP Scope

### In Scope (Must Have)

#### 1. Temporal Workflow Orchestration

- Order processing workflow with fraud check activity
- Mock fraud API with version-specific logic (v2.4.0 vs v2.4.1)
- Gradual rollout simulation (hash-based cohort assignment + date-based rollout)
- Search attributes: model_version, user_cohort, decision, fraud_score
- Event History capturing complete input/output for every decision

#### 2. Data Generation

- 10,000 synthetic orders using Faker (realistic users, amounts, countries)
- Timestamps spread over 7-day period simulating gradual rollout:
  - Days 1-2: 100% on v2.4.0 (baseline)
  - Day 3: 10% on v2.4.1, 90% on v2.4.0 (canary)
  - Days 4-5: 50% on v2.4.1, 50% on v2.4.0 (rollout)
  - Days 6-7: 100% on v2.4.1 (complete)
- Model version logic creates measurable differences (v2.4.1 = higher decline rate)

#### 3. Data Export & Warehouse

- Export Temporal Event Histories to DuckDB (local data warehouse)
- Tables:
  - **workflows:** One row per workflow execution (order_id, user_id, model_version, decision, score, timestamp)
  - **activity_executions:** One row per activity (inputs, outputs, duration, retries)
- SQL-queryable for analytics

#### 4. Investigation Dashboard

- Time series visualization: Fraud decline rate over time
- Automatic spike detection (statistical threshold)
- Drill-down: Click spike → see contributing workflow IDs
- Workflow detail view: Event History timeline with inputs/outputs
- Built with: Streamlit or Gradio (fast prototyping)

#### 5. AI Investigation Agent

- Natural language query interface (chat UI)
- Tools available to agent:
  - `query_temporal_workflows(search_attributes)` - Query Temporal Visibility API
  - `get_workflow_history(workflow_id)` - Retrieve complete Event History
  - `analyze_patterns(workflow_ids, group_by)` - Query DuckDB for aggregations
  - `compare_versions(version_a, version_b, metric)` - Statistical comparison
- LLM: Claude (Anthropic) or GPT-4 (OpenAI)
- Example queries it should handle:
  - "Why did fraud declines spike on Jan 16?"
  - "Show me decline rates by model version"
  - "Are international orders affected differently?"
  - "What percentage of high-value orders (>$500) are declined on each version?"

#### 6. Documentation

- README with setup instructions
- Architecture diagram
- Demo video (5 min walkthrough)
- Blog post: "Building AI-powered investigation tools for Temporal"

### Out of Scope (Not for MVP)

- ❌ Real fraud API integration (mock only)
- ❌ Production deployment (local Docker only)
- ❌ Multi-user auth/accounts
- ❌ Custom Search Attributes registration automation
- ❌ Batch remediation execution (documentation only)
- ❌ Real-time alerting (manual refresh only)
- ❌ Multiple LLM providers (pick one)
- ❌ Advanced visualizations (stick to basic charts)
- ❌ Mobile/responsive UI
- ❌ Other verticals (healthcare, content moderation - future)

## Technical Architecture

### System Components

```
┌─────────────────────────────────────────────────────────┐
│                  USER INTERFACE                         │
│  ┌──────────────────┐    ┌─────────────────────────┐   │
│  │  Dashboard       │    │  AI Agent Chat          │   │
│  │  (Streamlit)     │    │  (LangChain + Claude)   │   │
│  │  - Time series   │    │  - Natural language     │   │
│  │  - Spike alerts  │    │  - Tool calling         │   │
│  │  - Drill-down    │    │  - Explanations         │   │
│  └────────┬─────────┘    └───────────┬─────────────┘   │
└───────────┼──────────────────────────┼─────────────────┘
            │                          │
            ▼                          ▼
┌─────────────────────────────────────────────────────────┐
│               TEMPORAL ORCHESTRATION                    │
│  ┌────────────────────────────────────────────────┐    │
│  │  OrderFraudWorkflow                            │    │
│  │  - Input: Order (id, user, amount, countries)  │    │
│  │  - Activity: check_fraud_score(order, version) │    │
│  │  - Output: FraudResult (score, decision)       │    │
│  │  - Search Attrs: model_version, decision       │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
│  Temporal Server (Docker local)                        │
│  - Event History: Complete audit trail                 │
│  - Visibility API: Query workflows                     │
└─────────────┬───────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│                 DATA LAYER                              │
│  ┌──────────────────┐      ┌─────────────────────┐     │
│  │  Mock Fraud API  │      │  DuckDB Warehouse   │     │
│  │  - v2.4.0 logic  │      │  - workflows table  │     │
│  │  - v2.4.1 logic  │      │  - activities table │     │
│  │  - Scoring rules │      │  - SQL queries      │     │
│  └──────────────────┘      └─────────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

### Technology Stack

**Core:**
- Python 3.9+ - Primary language
- Temporal - Workflow orchestration (Docker local deployment)
- DuckDB - Embedded analytical database

**Data Generation:**
- Faker - Synthetic data generation

**UI:**
- Streamlit - Dashboard (or Gradio if preferred)

**AI Agent:**
- LangChain - Agent framework
- Claude 3.5 Sonnet - LLM for reasoning (via Anthropic API)
- Tools: Python functions wrapped as LangChain tools

**Development:**
- uv - Fast Python package manager (optional, can use pip)
- Git - Version control
- Docker - Temporal server

### Data Models

**Order (Input):**

```python
@dataclass
class Order:
    order_id: str
    user_id: str
    amount: float
    shipping_country: str
    billing_country: str
    timestamp: str  # ISO format
```

**FraudResult (Output):**

```python
@dataclass
class FraudResult:
    score: int  # 0-100
    decision: str  # 'approve' or 'decline'
    model_version: str  # 'v2.4.0' or 'v2.4.1'
    reason_codes: list[str]  # ['high_value', 'velocity_check_v2', ...]
```

### Workflow Definition

```python
@workflow.defn
class OrderFraudWorkflow:
    @workflow.run
    async def run(self, order: Order) -> FraudResult:
        # Determine model version (hash + date-based)
        model_version = self._assign_version(order)

        # Call fraud scoring activity
        result = await workflow.execute_activity(
            check_fraud_score,
            args=[order, model_version],
            start_to_close_timeout=timedelta(seconds=10)
        )

        return result

    def _assign_version(self, order: Order) -> str:
        """Gradual rollout logic"""
        cohort = hash(order.user_id) % 100
        order_date = datetime.fromisoformat(order.timestamp)

        # Rollout schedule
        if order_date < ROLLOUT_START:
            return "v2.4.0"  # Baseline
        elif order_date < CANARY_END:
            return "v2.4.1" if cohort < 10 else "v2.4.0"  # 10% canary
        elif order_date < ROLLOUT_END:
            return "v2.4.1" if cohort < 50 else "v2.4.0"  # 50% rollout
        else:
            return "v2.4.1"  # 100% rollout
```

### Mock Fraud Scoring Logic

Key difference between versions:

```python
# v2.4.0 - Less sensitive to velocity
if model_version == "v2.4.0":
    velocity_penalty = user_recent_orders * 5

# v2.4.1 - MORE sensitive to velocity (causes spike)
elif model_version == "v2.4.1":
    velocity_penalty = user_recent_orders * 15
```

This creates measurable difference that AI agent can detect.

### AI Agent Tools

**1. query_temporal_workflows**

```python
def query_temporal_workflows(
    start_time: str,
    end_time: str,
    filters: dict = None
) -> list[dict]:
    """Query Temporal Visibility API

    Example filters:
    - {"model_version": "v2.4.1"}
    - {"decision": "decline"}
    - {"fraud_score": {"gte": 70}}
    """
    # Calls Temporal Client.list_workflows()
    # Returns: list of workflow summaries
```

**2. get_workflow_history**

```python
def get_workflow_history(workflow_id: str) -> dict:
    """Retrieve complete Event History for a workflow"""
    # Calls Temporal Client.get_workflow_history()
    # Returns: Full event list with inputs/outputs
```

**3. analyze_patterns**

```python
def analyze_patterns(
    workflow_ids: list[str],
    group_by: str,
    metric: str = "decline_rate"
) -> dict:
    """Aggregate analysis across workflows

    Example:
    group_by="model_version", metric="decline_rate"
    → {"v2.4.0": 0.08, "v2.4.1": 0.16}
    """
    # Queries DuckDB
    # Returns: Grouped aggregations
```

**4. compare_versions**

```python
def compare_versions(
    version_a: str,
    version_b: str,
    time_range: tuple[str, str]
) -> dict:
    """Statistical comparison between versions"""
    # Returns: decline rates, sample sizes, examples
```

## Success Metrics (MVP Validation)

### Technical Success

- ✅ 10,000 workflows execute successfully
- ✅ Event Histories contain complete input/output data
- ✅ Export to DuckDB completes within 5 minutes
- ✅ AI agent correctly identifies model version as cause of spike
- ✅ Dashboard loads in <2 seconds

### Product Success

- ✅ Demo shows investigation completed in <60 seconds (vs 2-3 days manual)
- ✅ AI agent provides accurate root cause in 3/3 test scenarios
- ✅ Non-Temporal engineers can understand the demo
- ✅ GitHub repo gets 10+ stars in first week
- ✅ 2+ engineers express interest in collaborating

### Learning Success

- ✅ Validated that Temporal + AI agents is feasible architecture
- ✅ Identified 3+ real pain points from user feedback
- ✅ Decided on next vertical to test (healthcare, content mod, credit)

## Open Questions / Decisions Needed

**Q1: Which LLM to use?**
- **Option A:** Claude 3.5 Sonnet (Anthropic) - Better reasoning, tool use
- **Option B:** GPT-4 (OpenAI) - More familiar, cheaper
- **Decision:** Start with Claude (author preference), make swappable

**Q2: Dashboard framework?**
- **Option A:** Streamlit - Faster prototyping, Python-native
- **Option B:** Gradio - Better for chat interfaces
- **Decision:** Streamlit for dashboard, Gradio for AI chat (use both)

**Q3: How to handle Search Attributes?**
- **Issue:** Custom search attributes require registration
- **Option A:** Use default CustomKeywordField (hacky but works)
- **Option B:** Automate registration via Temporal CLI
- **Option C:** Document manual registration steps
- **Decision:** Option C for MVP (manual one-time setup)

**Q4: Real-time vs batch data export?**
- **Option A:** Export hourly (like Temporal Cloud)
- **Option B:** Export on-demand when user queries
- **Option C:** Export once after all workflows complete
- **Decision:** Option C for MVP (simplest)

## Development Plan

### Phase 1: Core Infrastructure (Days 1-3)

- Set up project structure
- Temporal workflows + activities
- Mock fraud API with version logic
- Data models
- **Deliverable:** Single workflow executes, visible in Temporal UI

### Phase 2: Data Generation (Days 4-5)

- Faker integration for synthetic orders
- Gradual rollout simulation (date-based)
- Generate 10K workflows
- **Deliverable:** 10K workflows in Temporal with realistic patterns

### Phase 3: Data Export (Days 6-7)

- Export Event Histories to DuckDB
- Create analytics tables
- Verify data quality
- **Deliverable:** DuckDB with queryable workflow data

### Phase 4: Dashboard (Days 8-9)

- Time series visualization
- Spike detection
- Workflow drill-down
- **Deliverable:** Working dashboard showing the spike

### Phase 5: AI Agent (Days 10-12)

- LangChain agent setup
- Tool implementations
- Chat interface
- **Deliverable:** Agent answers "Why did declines spike?"

### Phase 6: Polish & Documentation (Days 13-14)

- README
- Demo video
- Blog post
- Architecture diagram
- **Deliverable:** Presentable open-source project

## Future Enhancements (Post-MVP)

### Near-term (Weeks 3-4)

- Multi-vertical support (content moderation, credit scoring)
- Real-time alerting
- Batch remediation execution
- Better visualizations

### Medium-term (Months 2-3)

- Temporal Cloud integration
- Custom search attributes automation
- Advanced agent capabilities (counterfactual simulation)
- Web-based deployment

### Long-term (Months 4-6)

- Commercial SaaS offering
- Real third-party integrations (Stripe, Sift, etc.)
- Enterprise features (SSO, RBAC, audit logs)
- Multi-tenant support

## Risks & Mitigations

**Risk 1: AI agent hallucinates or gives wrong answers**
- **Mitigation:** Constrain to structured tools only (no free-form SQL)
- **Validation:** Manually verify agent answers against ground truth

**Risk 2: Temporal complexity too high for target users**
- **Mitigation:** Abstract Temporal behind simple API/UI
- **Validation:** Demo to non-Temporal engineers, measure comprehension

**Risk 3: Demo scenario not realistic enough**
- **Mitigation:** User research with fraud teams, iterate on scenario
- **Validation:** Show to 3+ domain experts, get feedback

**Risk 4: Performance issues with 10K workflows**
- **Mitigation:** Start with 1K, scale up gradually
- **Validation:** Benchmark query times, optimize if >5 seconds

## Appendix: Example Agent Interaction

**User:** "Why did fraud declines spike on January 16th?"

**Agent (thinking):**

```
1. Query workflows for Jan 16
2. Group by model_version
3. Calculate decline rates per version
4. Compare to baseline (Jan 14-15)
5. Identify statistical significance
6. Provide examples
```

**Agent (response):**

```
I analyzed 1,247 order workflows from January 16th and found the spike
is entirely driven by fraud model v2.4.1.

Key findings:
- v2.4.0 decline rate: 8.2% (consistent with baseline)
- v2.4.1 decline rate: 16.4% (2x higher than baseline)
- v2.4.1 was running on 50% of traffic that day (canary rollout)

Root cause: The new model (v2.4.1) applies a 3x higher penalty for
user velocity (recent orders in 24h), causing it to decline legitimate
repeat customers.

Example workflows showing the difference:
- order-00432 (v2.4.0): 3 orders/day → score 42 → APPROVED
- order-00891 (v2.4.1): 3 orders/day → score 73 → DECLINED

Would you like me to:
1. Show more examples
2. Analyze which customer segments are most affected
3. Estimate impact if we rollback to v2.4.0
```
