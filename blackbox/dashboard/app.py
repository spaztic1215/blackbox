"""Blackbox Investigation Dashboard.

Streamlit app for visualising the fraud model rollout and investigating
the decline-rate spike caused by v2.4.1.

Run:
    streamlit run blackbox/dashboard/app.py
"""

import json

import duckdb
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from blackbox import config

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Blackbox Dashboard",
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

@st.cache_resource
def get_connection():
    return duckdb.connect(config.DUCKDB_PATH, read_only=True)


@st.cache_data(ttl=60)
def load_overview_metrics() -> dict:
    con = get_connection()
    rows = con.execute("""
        SELECT
            model_version,
            COUNT(*) AS total,
            SUM(CASE WHEN decision = 'decline' THEN 1 ELSE 0 END) AS declines
        FROM workflows
        GROUP BY model_version
    """).fetchall()

    result: dict = {"total": 0, "declines": 0, "by_version": {}}
    for version, total, declines in rows:
        result["total"] += total
        result["declines"] += declines
        result["by_version"][version] = {
            "total": total,
            "declines": declines,
            "decline_rate": round(declines / total * 100, 2) if total else 0,
        }
    result["decline_rate"] = (
        round(result["declines"] / result["total"] * 100, 2)
        if result["total"]
        else 0
    )
    return result


@st.cache_data(ttl=60)
def load_daily_decline_rates() -> pd.DataFrame:
    con = get_connection()
    return con.execute("""
        SELECT
            CAST(timestamp AS DATE) AS date,
            model_version,
            COUNT(*) AS total,
            SUM(CASE WHEN decision = 'decline' THEN 1 ELSE 0 END) AS declines,
            ROUND(
                SUM(CASE WHEN decision = 'decline' THEN 1 ELSE 0 END) * 100.0
                / COUNT(*), 2
            ) AS decline_rate
        FROM workflows
        GROUP BY CAST(timestamp AS DATE), model_version
        ORDER BY date
    """).df()


@st.cache_data(ttl=60)
def load_daily_overall() -> pd.DataFrame:
    con = get_connection()
    return con.execute("""
        SELECT
            CAST(timestamp AS DATE) AS date,
            COUNT(*) AS total,
            SUM(CASE WHEN decision = 'decline' THEN 1 ELSE 0 END) AS declines,
            ROUND(
                SUM(CASE WHEN decision = 'decline' THEN 1 ELSE 0 END) * 100.0
                / COUNT(*), 2
            ) AS decline_rate
        FROM workflows
        GROUP BY CAST(timestamp AS DATE)
        ORDER BY date
    """).df()


@st.cache_data(ttl=60)
def load_version_stats() -> pd.DataFrame:
    con = get_connection()
    return con.execute("""
        SELECT
            model_version,
            COUNT(*) AS total_orders,
            SUM(CASE WHEN decision = 'decline' THEN 1 ELSE 0 END) AS declines,
            ROUND(
                SUM(CASE WHEN decision = 'decline' THEN 1 ELSE 0 END) * 100.0
                / COUNT(*), 2
            ) AS decline_rate_pct,
            ROUND(AVG(fraud_score), 1) AS avg_fraud_score,
            ROUND(AVG(amount), 2) AS avg_amount
        FROM workflows
        GROUP BY model_version
        ORDER BY model_version
    """).df()


@st.cache_data(ttl=60)
def load_workflows_for_date(date_str: str) -> pd.DataFrame:
    con = get_connection()
    return con.execute("""
        SELECT
            workflow_id, order_id, user_id, model_version,
            decision, fraud_score, amount, shipping_country, reason_codes
        FROM workflows
        WHERE CAST(timestamp AS DATE) = ?
        ORDER BY decision DESC, fraud_score DESC
    """, [date_str]).df()


@st.cache_data(ttl=60)
def load_workflow_detail(workflow_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = get_connection()
    wf = con.execute("SELECT * FROM workflows WHERE workflow_id = ?", [workflow_id]).df()
    acts = con.execute(
        "SELECT * FROM activity_executions WHERE workflow_id = ? ORDER BY scheduled_time",
        [workflow_id],
    ).df()
    return wf, acts


# ---------------------------------------------------------------------------
# Spike detection
# ---------------------------------------------------------------------------

def detect_spikes(daily_df: pd.DataFrame, window: int = 3, threshold: float = 2.0) -> pd.DataFrame:
    df = daily_df.copy()
    df["rolling_mean"] = df["decline_rate"].rolling(window, min_periods=1).mean()
    df["rolling_std"] = df["decline_rate"].rolling(window, min_periods=1).std().fillna(0)
    df["upper_bound"] = df["rolling_mean"] + threshold * df["rolling_std"]
    df["is_spike"] = df["decline_rate"] > df["upper_bound"]
    return df


# ---------------------------------------------------------------------------
# Visualizations
# ---------------------------------------------------------------------------

VERSION_COLORS = {config.MODEL_VERSION_OLD: "#636EFA", config.MODEL_VERSION_NEW: "#EF553B"}

PHASE_BANDS = [
    ("Baseline", config.ROLLOUT_BASE_DATE, config.BASELINE_END, "rgba(99,110,250,0.08)"),
    ("Canary (10%)", config.BASELINE_END, config.CANARY_END, "rgba(255,161,90,0.10)"),
    ("Rollout (50%)", config.CANARY_END, config.ROLLOUT_END, "rgba(239,85,59,0.10)"),
    ("Full (100%)", config.ROLLOUT_END, config.FULL_ROLLOUT_END, "rgba(239,85,59,0.15)"),
]


def build_time_series(daily_by_version: pd.DataFrame, spike_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()

    # Rollout phase bands
    for label, start, end, color in PHASE_BANDS:
        fig.add_vrect(
            x0=start, x1=end,
            fillcolor=color, layer="below", line_width=0,
            annotation_text=label, annotation_position="top left",
            annotation_font_size=10, annotation_font_color="gray",
        )

    # One trace per model version
    for version, color in VERSION_COLORS.items():
        vdf = daily_by_version[daily_by_version["model_version"] == version]
        fig.add_trace(go.Scatter(
            x=vdf["date"], y=vdf["decline_rate"],
            mode="lines+markers", name=version,
            line=dict(color=color, width=2),
            marker=dict(size=7),
        ))

    # Spike markers
    spikes = spike_df[spike_df["is_spike"]]
    if not spikes.empty:
        fig.add_trace(go.Scatter(
            x=spikes["date"], y=spikes["decline_rate"],
            mode="markers", name="Spike",
            marker=dict(color="red", size=14, symbol="star"),
            showlegend=True,
        ))

    fig.update_layout(
        title="Daily Fraud Decline Rate by Model Version",
        xaxis_title="Date",
        yaxis_title="Decline Rate (%)",
        yaxis_rangemode="tozero",
        hovermode="x unified",
        height=420,
        margin=dict(t=60, b=40),
    )
    return fig


def build_comparison_bar(stats_df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for _, row in stats_df.iterrows():
        fig.add_trace(go.Bar(
            x=["Decline Rate (%)"],
            y=[row["decline_rate_pct"]],
            name=row["model_version"],
            marker_color=VERSION_COLORS.get(row["model_version"], "gray"),
            text=[f"{row['decline_rate_pct']}%"],
            textposition="auto",
        ))
    fig.update_layout(
        title="Decline Rate Comparison",
        barmode="group",
        height=350,
        yaxis_title="Decline Rate (%)",
        yaxis_rangemode="tozero",
        margin=dict(t=50, b=30),
    )
    return fig


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

def main():
    st.title("Blackbox: Fraud Model Rollout Investigation")
    st.caption(
        f"Rollout window: **{config.ROLLOUT_BASE_DATE.strftime('%b %d')}** – "
        f"**{config.FULL_ROLLOUT_END.strftime('%b %d, %Y')}**  ·  "
        f"{config.MODEL_VERSION_OLD} → {config.MODEL_VERSION_NEW}"
    )

    # -- Overview Metrics ----------------------------------------------------
    metrics = load_overview_metrics()
    old = metrics["by_version"].get(config.MODEL_VERSION_OLD, {})
    new = metrics["by_version"].get(config.MODEL_VERSION_NEW, {})

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Workflows", f"{metrics['total']:,}")
    c2.metric("Overall Decline Rate", f"{metrics['decline_rate']}%")
    c3.metric(f"{config.MODEL_VERSION_OLD} Decline Rate", f"{old.get('decline_rate', 0)}%")
    delta = round(new.get("decline_rate", 0) - old.get("decline_rate", 0), 2)
    c4.metric(
        f"{config.MODEL_VERSION_NEW} Decline Rate",
        f"{new.get('decline_rate', 0)}%",
        delta=f"{delta:+}pp vs {config.MODEL_VERSION_OLD}",
        delta_color="inverse",
    )

    st.divider()

    # -- Time Series ---------------------------------------------------------
    daily_by_version = load_daily_decline_rates()
    daily_overall = load_daily_overall()
    spike_df = detect_spikes(daily_overall)

    st.plotly_chart(build_time_series(daily_by_version, spike_df), use_container_width=True)

    spike_dates = spike_df[spike_df["is_spike"]]["date"].tolist()
    if spike_dates:
        dates_str = ", ".join(str(d) for d in spike_dates)
        st.warning(
            f"Spike detected on **{dates_str}** — decline rate exceeded "
            "statistical threshold (rolling mean + 2 std dev)."
        )

    st.divider()

    # -- Model Comparison ----------------------------------------------------
    st.subheader("Model Comparison")
    stats_df = load_version_stats()

    left, right = st.columns(2)
    with left:
        st.plotly_chart(build_comparison_bar(stats_df), use_container_width=True)
    with right:
        st.dataframe(
            stats_df.rename(columns={
                "model_version": "Model Version",
                "total_orders": "Orders",
                "declines": "Declines",
                "decline_rate_pct": "Decline Rate %",
                "avg_fraud_score": "Avg Score",
                "avg_amount": "Avg Amount ($)",
            }),
            hide_index=True,
            use_container_width=True,
        )

    st.divider()

    # -- Date Drill-down -----------------------------------------------------
    st.subheader("Drill-down by Date")
    all_dates = sorted(daily_overall["date"].tolist())
    default_idx = 0
    if spike_dates:
        for i, d in enumerate(all_dates):
            if d == spike_dates[0]:
                default_idx = i
                break

    selected_date = st.selectbox(
        "Select a date to inspect",
        options=all_dates,
        index=default_idx,
        format_func=lambda d: str(d),
    )

    if selected_date is not None:
        wf_df = load_workflows_for_date(str(selected_date))
        st.caption(f"**{len(wf_df)}** workflows on {selected_date}")
        st.dataframe(
            wf_df,
            hide_index=True,
            use_container_width=True,
            height=350,
        )

        # -- Workflow Detail -------------------------------------------------
        if not wf_df.empty:
            st.subheader("Workflow Detail")
            wf_ids = wf_df["workflow_id"].tolist()
            selected_wf = st.selectbox("Select a workflow", options=wf_ids)

            if selected_wf:
                wf_row, acts_df = load_workflow_detail(selected_wf)

                if not wf_row.empty:
                    row = wf_row.iloc[0]
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown("**Workflow Summary**")
                        st.markdown(f"- **Order:** {row['order_id']}")
                        st.markdown(f"- **User:** {row['user_id']}")
                        st.markdown(f"- **Model:** {row['model_version']}")
                        st.markdown(f"- **Decision:** {row['decision']}")
                        st.markdown(f"- **Fraud Score:** {row['fraud_score']}")
                        st.markdown(f"- **Amount:** ${row['amount']:.2f}")
                        st.markdown(
                            f"- **Shipping:** {row['shipping_country']}  ·  "
                            f"**Billing:** {row['billing_country']}"
                        )
                    with col_b:
                        st.markdown("**Reason Codes**")
                        try:
                            codes = json.loads(row["reason_codes"])
                        except (json.JSONDecodeError, TypeError):
                            codes = row["reason_codes"]
                        st.json(codes)

                if not acts_df.empty:
                    st.markdown("**Activity Executions**")
                    for _, act in acts_df.iterrows():
                        with st.expander(f"{act['activity_type']}"):
                            mc1, mc2 = st.columns(2)
                            mc1.metric("Duration", f"{act['duration_ms']:.0f} ms")
                            mc2.metric("Retries", int(act["retry_count"]))
                            st.markdown("**Inputs**")
                            try:
                                st.json(json.loads(act["inputs"]))
                            except (json.JSONDecodeError, TypeError):
                                st.code(act["inputs"])
                            st.markdown("**Outputs**")
                            try:
                                st.json(json.loads(act["outputs"]))
                            except (json.JSONDecodeError, TypeError):
                                st.code(act["outputs"])


if __name__ == "__main__":
    main()
