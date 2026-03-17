# Blackbox

**AI-powered investigation for third-party integrations**

Blackbox orchestrates third-party API calls as [Temporal](https://temporal.io) workflows — giving you a complete audit trail — then uses AI agents to investigate anomalies in seconds instead of days.

## The Demo Scenario

An e-commerce company rolls out fraud model **v2.4.1** gradually:

| Days | v2.4.0 | v2.4.1 | Phase |
|------|--------|--------|-------|
| 1–2  | 100%   | 0%     | Baseline |
| 3    | 90%    | 10%    | Canary |
| 4–5  | 50%    | 50%    | Rollout |
| 6–7  | 0%     | 100%   | Full |

On day 4, the fraud decline rate spikes from ~8% to ~16%. The AI agent identifies the root cause in 30 seconds: v2.4.1's velocity penalty is 3× more aggressive, declining legitimate repeat customers.

## Quick Start

### Prerequisites

- Python 3.10+
- Docker & Docker Compose
- Temporal CLI (`brew install temporal` or [download](https://docs.temporal.io/cli))

### 1. Start Temporal

```bash
docker compose up -d
```

### 2. Register Search Attributes

Run this **on your host machine** (not inside the container). It connects to the Temporal server via the exposed port.

**Option A** — If you have the `temporal` CLI installed:
```bash
bash scripts/register_search_attributes.sh
```

**Option B** — Using Docker (no CLI needed):
```bash
docker compose exec temporal temporal operator search-attribute create \
  --namespace default --name BlackboxModelVersion --type Keyword
docker compose exec temporal temporal operator search-attribute create \
  --namespace default --name BlackboxDecision --type Keyword
docker compose exec temporal temporal operator search-attribute create \
  --namespace default --name BlackboxFraudScore --type Int
docker compose exec temporal temporal operator search-attribute create \
  --namespace default --name BlackboxUserCohort --type Int
docker compose exec temporal temporal operator search-attribute create \
  --namespace default --name BlackboxShippingCountry --type Keyword
docker compose exec temporal temporal operator search-attribute create \
  --namespace default --name BlackboxOrderAmount --type Double
```

### 3. Install Dependencies

```bash
pip install -e ".[dev]"
```

### 4. Start the Worker

```bash
python -m blackbox.worker
```

### 5. Run the Simulation

```bash
python scripts/run_simulation.py --count 10000
```

### 6. Export to DuckDB

Once the simulation completes, export workflow histories to a local DuckDB warehouse:

```bash
python scripts/export_to_duckdb.py
```

This creates `blackbox_warehouse.duckdb` with two tables:
- **`workflows`** — one row per workflow (order metadata + fraud decision)
- **`activity_executions`** — one row per activity (inputs, outputs, duration, retries)

You can query the data directly:

```bash
python -c "
import duckdb
con = duckdb.connect('blackbox_warehouse.duckdb')
con.sql('SELECT model_version, decision, COUNT(*) FROM workflows GROUP BY ALL').show()
con.sql('SELECT COUNT(*) FROM activity_executions').show()
"
```

### 7. Launch the Dashboard

```bash
streamlit run blackbox/dashboard/app.py
```

Opens a browser with:
- Overview metrics (total workflows, decline rates by model version)
- Time series chart showing the decline-rate spike with rollout phase annotations
- Automatic spike detection
- Date drill-down to inspect individual workflows and activity event histories

### 8. Validate Data (optional)

Preview order distributions and simulated decline rates without Temporal:

```bash
python scripts/validate_data.py --count 10000
```

### 9. Run Tests

```bash
pytest tests/ -v
```

## Project Structure

```
blackbox/
├── blackbox/
│   ├── activities/        # Temporal activity implementations
│   │   └── fraud_check.py # Wraps the mock fraud API
│   ├── agent/             # AI investigation agent (Phase 5)
│   ├── dashboard/         # Streamlit dashboard
│   │   └── app.py         # Investigation dashboard UI
│   ├── export/            # DuckDB export
│   │   └── duckdb_export.py # Export Temporal histories → DuckDB
│   ├── fraud_api/         # Mock fraud scoring engine
│   │   └── scorer.py      # v2.4.0 vs v2.4.1 logic
│   ├── models/            # Data models (Order, FraudResult)
│   │   └── data.py
│   ├── utils/             # Data generation, helpers
│   │   └── data_generator.py
│   ├── workflows/         # Temporal workflow definitions
│   │   └── order_fraud.py # OrderFraudWorkflow
│   ├── config.py          # All configuration constants
│   └── worker.py          # Temporal worker process
├── scripts/
│   ├── export_to_duckdb.py
│   ├── register_search_attributes.sh
│   ├── run_simulation.py
│   └── validate_data.py
├── tests/
│   └── test_core.py
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## Architecture

```
┌─────────────────────┐    ┌─────────────────────┐
│  Dashboard          │    │  AI Agent Chat       │
│  (Streamlit)        │    │  (LangChain+Claude)  │
└─────────┬───────────┘    └──────────┬──────────┘
          │                           │
          ▼                           ▼
┌─────────────────────────────────────────────────┐
│  Temporal Server                                │
│  ┌───────────────────────────────────────────┐  │
│  │ OrderFraudWorkflow                        │  │
│  │  → assign model version (gradual rollout) │  │
│  │  → check_fraud_score activity             │  │
│  │  → upsert search attributes               │  │
│  └───────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
  ┌───────────────┐    ┌───────────────┐
  │ Mock Fraud API│    │ DuckDB        │
  │ (v2.4.0/v241) │    │ (warehouse)   │
  └───────────────┘    └───────────────┘
```

## License

MIT
