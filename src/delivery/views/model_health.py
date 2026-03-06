"""
BetVector — Model Health Page (E10-01)
=======================================
Displays calibration plots, Brier score trends, CLV tracking,
model comparison, ensemble weights, feature importance, and
market edge map.

This is the "how is the model doing?" interface — surfaces all
self-improvement metrics and historical performance data.

Sections:
1. Summary metrics — Brier score, ROI, total predictions, active models
2. Calibration plot — predicted probability vs actual win rate
3. Brier score trend — line chart over time (weekly)
4. CLV tracking — rolling average closing line value
5. Model comparison — side-by-side metrics when 2+ models active
6. Ensemble weights — horizontal bar showing weight allocation
7. Feature importance — top 15 features ranked by gain
8. Market Edge Map — heatmap of league × market performance
9. Recalibration history — past calibration events
10. Retrain history — past retrains with trigger reason

Master Plan refs: MP §3 Flow 4 (Model Health), MP §8 Design System,
MP §11 Self-Improvement Engine
"""

import json
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.database.db import get_session
from src.database.models import (
    BetLog,
    CalibrationHistory,
    EnsembleWeightHistory,
    FeatureImportanceLog,
    MarketPerformance,
    Match,
    ModelPerformance,
    Prediction,
    RetrainHistory,
)


# ============================================================================
# Design tokens (MP §8)
# ============================================================================

COLOURS = {
    "bg": "#0D1117",
    "surface": "#161B22",
    "border": "#30363D",
    "text": "#E6EDF3",
    "text_secondary": "#8B949E",
    "green": "#3FB950",
    "red": "#F85149",
    "yellow": "#D29922",
    "blue": "#58A6FF",
    "purple": "#BC8CFF",
}

# Assessment colours for the Market Edge Map (MP §11.4)
ASSESSMENT_COLOURS = {
    "profitable": COLOURS["green"],
    "promising": COLOURS["yellow"],
    "insufficient": "#484F58",  # Muted grey for insufficient data
    "unprofitable": COLOURS["red"],
}


# ============================================================================
# Data Loading
# ============================================================================

def load_calibration_data() -> Optional[Dict]:
    """Load the most recent calibration data from model_performance.

    The calibration_json field stores binned calibration stats —
    predicted_avg vs actual_rate for each probability bin.
    Returns None if no calibration data exists.
    """
    with get_session() as session:
        mp = (
            session.query(ModelPerformance)
            .filter(ModelPerformance.calibration_json.isnot(None))
            .order_by(ModelPerformance.computed_at.desc())
            .first()
        )
        if not mp or not mp.calibration_json:
            return None

        try:
            cal = json.loads(mp.calibration_json)
        except (json.JSONDecodeError, TypeError):
            return None

        return {
            "model_name": mp.model_name,
            "period_type": mp.period_type,
            "period_start": mp.period_start,
            "period_end": mp.period_end,
            "brier_score": mp.brier_score,
            "calibration": cal,
        }


def compute_live_brier_and_calibration() -> Optional[Dict]:
    """Compute Brier score and calibration from predictions + match results.

    Joins predictions with finished matches to calculate real-time
    calibration accuracy.  This gives us fresh data even if
    model_performance hasn't been updated recently.

    The Brier score measures how close predicted probabilities are to
    actual outcomes.  Lower is better:
    - 0.0 = perfect predictions
    - 0.25 = no better than random guessing (for 1X2 markets)
    """
    with get_session() as session:
        results = (
            session.query(Prediction, Match)
            .join(Match, Prediction.match_id == Match.id)
            .filter(
                Match.status == "finished",
                Match.home_goals.isnot(None),
            )
            .order_by(Match.date.asc())
            .all()
        )

    if not results:
        return None

    # Build lists for Brier score and calibration
    brier_scores = []
    prob_actual_pairs = []  # (predicted_prob, actual_outcome, date)

    for pred, match in results:
        # Determine actual outcome
        if match.home_goals > match.away_goals:
            actual = [1, 0, 0]  # Home win
        elif match.home_goals == match.away_goals:
            actual = [0, 1, 0]  # Draw
        else:
            actual = [0, 0, 1]  # Away win

        predicted = [
            pred.prob_home_win or 0,
            pred.prob_draw or 0,
            pred.prob_away_win or 0,
        ]

        # Brier score: mean squared error of probability estimates
        brier = sum((p - a) ** 2 for p, a in zip(predicted, actual)) / 3
        brier_scores.append({"date": match.date, "brier": brier})

        # Collect each prediction-outcome pair for calibration
        for prob, outcome in zip(predicted, actual):
            prob_actual_pairs.append((prob, outcome, match.date))

    # Overall Brier score
    overall_brier = np.mean([b["brier"] for b in brier_scores])

    # Weekly Brier trend
    brier_df = pd.DataFrame(brier_scores)
    brier_df["week"] = pd.to_datetime(brier_df["date"]).dt.isocalendar().week.astype(str)
    brier_df["year_week"] = pd.to_datetime(brier_df["date"]).dt.strftime("%Y-W%U")
    weekly_brier = brier_df.groupby("year_week")["brier"].mean().reset_index()
    weekly_brier = weekly_brier.sort_values("year_week")

    # Calibration bins (10 bins from 0.0 to 1.0)
    calibration = {}
    for bin_start in np.arange(0, 1.0, 0.1):
        bin_end = bin_start + 0.1
        bin_label = f"{bin_start:.1f}-{bin_end:.1f}"

        in_bin = [(p, a) for p, a, _ in prob_actual_pairs if bin_start <= p < bin_end]
        if in_bin:
            predicted_avg = np.mean([p for p, _ in in_bin])
            actual_rate = np.mean([a for _, a in in_bin])
            calibration[bin_label] = {
                "predicted_avg": predicted_avg,
                "actual_rate": actual_rate,
                "count": len(in_bin),
            }

    return {
        "overall_brier": overall_brier,
        "weekly_brier": weekly_brier,
        "calibration": calibration,
        "total_predictions": len(brier_scores),
    }


def load_model_comparison() -> pd.DataFrame:
    """Load performance metrics for all active models.

    Returns a DataFrame with one row per model.  If only one model
    exists, model comparison table won't be shown (AC4 says 2+).
    """
    with get_session() as session:
        # Get the most recent season-level performance per model
        models = (
            session.query(ModelPerformance)
            .filter(ModelPerformance.period_type == "season")
            .order_by(ModelPerformance.computed_at.desc())
            .all()
        )

    if not models:
        return pd.DataFrame()

    # De-duplicate: keep latest per model_name
    seen = set()
    unique = []
    for mp in models:
        if mp.model_name not in seen:
            seen.add(mp.model_name)
            unique.append({
                "Model": mp.model_name,
                "Brier Score": mp.brier_score,
                "ROI %": mp.roi,
                "Avg CLV": mp.avg_clv,
                "Predictions": mp.total_predictions,
                "1X2 Win %": mp.win_rate_1x2,
                "O/U Win %": mp.win_rate_ou,
                "BTTS Win %": mp.win_rate_btts,
            })

    return pd.DataFrame(unique)


def load_ensemble_weights() -> List[Dict]:
    """Load the latest ensemble weight allocation per model."""
    with get_session() as session:
        rows = (
            session.query(EnsembleWeightHistory)
            .order_by(EnsembleWeightHistory.created_at.desc())
            .limit(20)
            .all()
        )

    if not rows:
        return []

    # Get the latest timestamp and return all weights from that batch
    latest_ts = rows[0].created_at
    return [
        {
            "model": r.model_name,
            "weight": r.weight,
            "brier": r.brier_score,
            "previous_weight": r.previous_weight,
        }
        for r in rows
        if r.created_at == latest_ts
    ]


def load_feature_importance() -> pd.DataFrame:
    """Load the most recent feature importance rankings.

    Returns top 15 features ranked by gain from the latest
    training cycle.
    """
    with get_session() as session:
        # Find latest training date
        latest = (
            session.query(FeatureImportanceLog.training_date)
            .order_by(FeatureImportanceLog.training_date.desc())
            .first()
        )
        if not latest:
            return pd.DataFrame()

        rows = (
            session.query(FeatureImportanceLog)
            .filter_by(training_date=latest[0])
            .order_by(FeatureImportanceLog.importance_rank.asc())
            .limit(15)
            .all()
        )

    return pd.DataFrame([
        {
            "Feature": r.feature_name,
            "Importance": r.importance_gain,
            "Rank": r.importance_rank,
        }
        for r in rows
    ])


def load_market_edge_map() -> pd.DataFrame:
    """Load the market performance heatmap data.

    Returns a DataFrame with league, market_type, roi, assessment
    for the most recent period.
    """
    with get_session() as session:
        rows = (
            session.query(MarketPerformance)
            .order_by(MarketPerformance.period_end.desc())
            .all()
        )

    if not rows:
        return pd.DataFrame()

    # Get the latest period_end and return all rows from that period
    latest_period = rows[0].period_end
    return pd.DataFrame([
        {
            "League": r.league,
            "Market": r.market_type,
            "ROI %": r.roi,
            "Bets": r.total_bets,
            "Assessment": r.assessment,
            "CI Lower": r.roi_ci_lower,
            "CI Upper": r.roi_ci_upper,
        }
        for r in rows
        if r.period_end == latest_period
    ])


def load_calibration_history() -> pd.DataFrame:
    """Load past calibration events for the recalibration history table."""
    with get_session() as session:
        rows = (
            session.query(CalibrationHistory)
            .order_by(CalibrationHistory.created_at.desc())
            .limit(20)
            .all()
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame([
        {
            "Date": r.created_at[:10] if r.created_at else "—",
            "Model": r.model_name,
            "Method": r.calibration_method,
            "Samples": r.sample_size,
            "Error Before": f"{r.mean_abs_error_before:.3f}" if r.mean_abs_error_before else "—",
            "Error After": f"{r.mean_abs_error_after:.3f}" if r.mean_abs_error_after else "—",
            "Active": "Yes" if r.is_active else "No",
            "Rolled Back": "Yes" if r.rolled_back else "No",
        }
        for r in rows
    ])


def load_retrain_history() -> pd.DataFrame:
    """Load past retrain events for the retrain history table."""
    with get_session() as session:
        rows = (
            session.query(RetrainHistory)
            .order_by(RetrainHistory.created_at.desc())
            .limit(20)
            .all()
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame([
        {
            "Date": r.created_at[:10] if r.created_at else "—",
            "Model": r.model_name,
            "Trigger": r.trigger_type,
            "Reason": r.trigger_reason or "—",
            "Brier Before": f"{r.brier_before:.4f}" if r.brier_before else "—",
            "Brier After": f"{r.brier_after:.4f}" if r.brier_after else "—",
            "Samples": r.training_samples,
            "Rolled Back": "Yes" if r.was_rolled_back else "No",
        }
        for r in rows
    ])


# ============================================================================
# Charts
# ============================================================================

def create_calibration_chart(calibration: Dict) -> go.Figure:
    """Create a calibration plot — predicted probability vs actual win rate.

    A perfectly calibrated model would have all points on the diagonal
    line.  Points above the diagonal mean the model is underconfident
    (things happen more often than predicted), below means overconfident.

    Point sizes are scaled by sample count per bin so you can see
    which probability ranges have the most data.
    """
    bins = sorted(calibration.keys())
    predicted = [calibration[b]["predicted_avg"] for b in bins]
    actual = [calibration[b]["actual_rate"] for b in bins]
    counts = [calibration[b]["count"] for b in bins]

    # Scale marker sizes: min 8, max 30, proportional to count
    max_count = max(counts) if counts else 1
    sizes = [max(8, min(30, (c / max_count) * 30)) for c in counts]

    fig = go.Figure()

    # Diagonal reference line (perfect calibration)
    fig.add_trace(go.Scatter(
        x=[0, 1], y=[0, 1],
        mode="lines",
        line=dict(color=COLOURS["border"], width=1, dash="dash"),
        showlegend=False,
        hoverinfo="skip",
    ))

    # Calibration points
    fig.add_trace(go.Scatter(
        x=predicted,
        y=actual,
        mode="markers+lines",
        marker=dict(
            size=sizes,
            color=COLOURS["blue"],
            line=dict(color=COLOURS["text"], width=1),
        ),
        line=dict(color=COLOURS["blue"], width=1),
        text=[f"Bin: {b}<br>Predicted: {p:.1%}<br>Actual: {a:.1%}<br>Count: {c}"
              for b, p, a, c in zip(bins, predicted, actual, counts)],
        hovertemplate="%{text}<extra></extra>",
    ))

    fig.update_layout(
        title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="JetBrains Mono, monospace",
            color=COLOURS["text_secondary"],
            size=12,
        ),
        xaxis=dict(
            title="Predicted Probability",
            range=[0, 1],
            gridcolor=COLOURS["border"],
            showgrid=True,
            dtick=0.1,
        ),
        yaxis=dict(
            title="Actual Win Rate",
            range=[0, 1],
            gridcolor=COLOURS["border"],
            showgrid=True,
            dtick=0.1,
        ),
        margin=dict(l=60, r=20, t=10, b=50),
        height=400,
        showlegend=False,
    )

    return fig


def create_brier_trend_chart(weekly_brier: pd.DataFrame) -> go.Figure:
    """Create a line chart of weekly Brier scores over time.

    The Brier score measures prediction accuracy — lower is better.
    A score of 0.25 means no better than random guessing for 1X2
    markets.  Good models should be well below 0.25.
    """
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=weekly_brier["year_week"],
        y=weekly_brier["brier"],
        mode="lines+markers",
        line=dict(color=COLOURS["blue"], width=2),
        marker=dict(size=6, color=COLOURS["blue"]),
        hovertemplate="Week: %{x}<br>Brier: %{y:.4f}<extra></extra>",
    ))

    # Reference line at 0.25 (random guessing for 1X2)
    fig.add_hline(
        y=0.25, line_dash="dash",
        line_color=COLOURS["red"], line_width=1,
        annotation_text="Random (0.25)",
        annotation_position="top right",
        annotation_font=dict(color=COLOURS["red"], size=10),
    )

    fig.update_layout(
        title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="JetBrains Mono, monospace",
            color=COLOURS["text_secondary"],
            size=12,
        ),
        xaxis=dict(
            gridcolor=COLOURS["border"],
            showgrid=True,
            title="",
        ),
        yaxis=dict(
            gridcolor=COLOURS["border"],
            showgrid=True,
            title="Brier Score",
        ),
        margin=dict(l=60, r=20, t=10, b=40),
        height=300,
        showlegend=False,
    )

    return fig


def create_feature_importance_chart(df: pd.DataFrame) -> go.Figure:
    """Create a horizontal bar chart of top 15 features by importance gain.

    Features are ranked by their contribution to model accuracy
    (using the XGBoost/LightGBM 'gain' importance method).
    """
    # Reverse order so highest importance is at top
    df_sorted = df.sort_values("Importance", ascending=True)

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df_sorted["Importance"],
        y=df_sorted["Feature"],
        orientation="h",
        marker_color=COLOURS["blue"],
        hovertemplate="Feature: %{y}<br>Importance: %{x:.4f}<extra></extra>",
    ))

    fig.update_layout(
        title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="JetBrains Mono, monospace",
            color=COLOURS["text_secondary"],
            size=11,
        ),
        xaxis=dict(
            gridcolor=COLOURS["border"],
            showgrid=True,
            title="Gain",
        ),
        yaxis=dict(
            gridcolor=COLOURS["border"],
            showgrid=False,
            title="",
        ),
        margin=dict(l=140, r=20, t=10, b=40),
        height=max(300, len(df_sorted) * 28),
        showlegend=False,
    )

    return fig


def create_ensemble_weights_chart(weights: List[Dict]) -> go.Figure:
    """Create a horizontal stacked bar showing ensemble weight allocation.

    Each model gets a section of the bar proportional to its weight.
    Weights are constrained by guardrails: min 10%, max 60%.
    """
    fig = go.Figure()

    model_colours = [COLOURS["blue"], COLOURS["green"], COLOURS["yellow"], COLOURS["purple"]]

    for i, w in enumerate(weights):
        colour = model_colours[i % len(model_colours)]
        fig.add_trace(go.Bar(
            x=[w["weight"] * 100],
            y=["Ensemble"],
            orientation="h",
            name=w["model"],
            marker_color=colour,
            text=[f"{w['model']}: {w['weight']:.0%}"],
            textposition="inside",
            textfont=dict(color=COLOURS["text"], size=12),
            hovertemplate=f"{w['model']}: {w['weight']:.1%}<br>Brier: {w['brier']:.4f}<extra></extra>",
        ))

    fig.update_layout(
        title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        barmode="stack",
        font=dict(
            family="JetBrains Mono, monospace",
            color=COLOURS["text_secondary"],
            size=12,
        ),
        xaxis=dict(
            title="Weight %",
            range=[0, 100],
            gridcolor=COLOURS["border"],
            showgrid=True,
        ),
        yaxis=dict(showticklabels=False),
        margin=dict(l=20, r=20, t=10, b=40),
        height=120,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.5,
            font=dict(color=COLOURS["text_secondary"]),
        ),
    )

    return fig


def create_market_edge_heatmap(df: pd.DataFrame) -> go.Figure:
    """Create a heatmap of league × market performance (Market Edge Map).

    Colour-coded by assessment tier (MP §11.4):
    - Green = Profitable (ROI positive, CI positive, 100+ bets)
    - Yellow = Promising (ROI positive but uncertain, 50-99 bets)
    - Grey = Insufficient data (< 50 bets)
    - Red = Unprofitable (ROI negative, CI negative, 100+ bets)
    """
    # Pivot data into a matrix
    leagues = sorted(df["League"].unique())
    markets = sorted(df["Market"].unique())

    # Build ROI matrix and assessment matrix
    roi_matrix = []
    text_matrix = []
    colour_matrix = []

    for league in leagues:
        roi_row = []
        text_row = []
        for market in markets:
            cell = df[(df["League"] == league) & (df["Market"] == market)]
            if cell.empty:
                roi_row.append(0)
                text_row.append("No data")
            else:
                row = cell.iloc[0]
                roi_row.append(row["ROI %"] or 0)
                text_row.append(
                    f"ROI: {row['ROI %']:.1f}%<br>"
                    f"Bets: {row['Bets']}<br>"
                    f"Assessment: {row['Assessment']}"
                )
        roi_matrix.append(roi_row)
        text_matrix.append(text_row)

    fig = go.Figure(data=go.Heatmap(
        z=roi_matrix,
        x=markets,
        y=leagues,
        text=text_matrix,
        texttemplate="%{z:.1f}%",
        textfont=dict(size=11, family="JetBrains Mono, monospace"),
        colorscale=[
            [0, COLOURS["red"]],
            [0.5, COLOURS["border"]],
            [1.0, COLOURS["green"]],
        ],
        zmid=0,
        showscale=True,
        colorbar=dict(
            title="ROI %",
            titlefont=dict(color=COLOURS["text_secondary"]),
            tickfont=dict(color=COLOURS["text_secondary"]),
        ),
        hovertemplate="%{text}<extra></extra>",
    ))

    fig.update_layout(
        title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="JetBrains Mono, monospace",
            color=COLOURS["text_secondary"],
            size=12,
        ),
        margin=dict(l=80, r=20, t=10, b=40),
        height=max(200, len(leagues) * 50 + 80),
    )

    return fig


# ============================================================================
# Page Layout
# ============================================================================

st.markdown(
    '<div class="bv-page-title">Model Health</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="text-muted">Calibration, accuracy, and model performance metrics</p>',
    unsafe_allow_html=True,
)
st.divider()

# --- Load all data ---
with st.spinner("Computing model metrics..."):
    live_data = compute_live_brier_and_calibration()
    stored_cal = load_calibration_data()
    model_comparison = load_model_comparison()
    ensemble_weights = load_ensemble_weights()
    feature_importance = load_feature_importance()
    market_edge = load_market_edge_map()
    cal_history = load_calibration_history()
    retrain_hist = load_retrain_history()


# --- Section 1: Summary Metrics ---
if live_data:
    brier_colour = COLOURS["green"] if live_data["overall_brier"] < 0.22 else (
        COLOURS["yellow"] if live_data["overall_brier"] < 0.25 else COLOURS["red"]
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f'<div>'
            f'<span style="font-family: \'Inter\', sans-serif; font-size: 12px; color: #8B949E; '
            f'text-transform: uppercase; letter-spacing: 0.5px;">Brier Score</span><br>'
            f'<span style="font-family: \'JetBrains Mono\', monospace; font-size: 28px; font-weight: 700; '
            f'color: {brier_colour};">{live_data["overall_brier"]:.4f}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.metric("Total Predictions", f"{live_data['total_predictions']:,}")
    with col3:
        # Show the active production model name from config (E25-04)
        try:
            from src.config import config
            active_models = list(config.settings.models.active_models)
            ensemble_on = getattr(config.settings.models, "ensemble_enabled", False)
            if ensemble_on and len(active_models) > 1:
                model_label = "Ensemble"
            elif active_models:
                model_label = active_models[0]
            else:
                model_label = "Unknown"
        except Exception:
            model_label = "poisson_v1"
        st.metric("Active Model", model_label)
    with col4:
        # Brier interpretation — anything below 0.25 beats random guessing
        if live_data["overall_brier"] < 0.20:
            quality = "Good"
            q_colour = COLOURS["green"]
        elif live_data["overall_brier"] < 0.25:
            quality = "Fair"
            q_colour = COLOURS["yellow"]
        else:
            quality = "Poor"
            q_colour = COLOURS["red"]

        st.markdown(
            f'<div>'
            f'<span style="font-family: \'Inter\', sans-serif; font-size: 12px; color: #8B949E; '
            f'text-transform: uppercase; letter-spacing: 0.5px;">Model Quality</span><br>'
            f'<span style="font-family: \'JetBrains Mono\', monospace; font-size: 28px; font-weight: 700; '
            f'color: {q_colour};">{quality}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    # --- Section 2: Calibration Plot ---
    calibration = live_data.get("calibration") or (stored_cal or {}).get("calibration")

    if calibration:
        st.markdown(
            '<div class="bv-section-header">Calibration Plot</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<p style="font-family: Inter, sans-serif; font-size: 13px; color: {COLOURS["text_secondary"]};">'
            "Points on the diagonal = perfectly calibrated. Above = underconfident, below = overconfident. "
            "Point size shows sample count per bin.</p>",
            unsafe_allow_html=True,
        )

        fig_cal = create_calibration_chart(calibration)
        st.plotly_chart(fig_cal, use_container_width=True, config={"displayModeBar": False})

        st.divider()

    # --- Section 3: Brier Score Trend ---
    if not live_data["weekly_brier"].empty and len(live_data["weekly_brier"]) > 1:
        st.markdown(
            '<div class="bv-section-header">Brier Score Trend</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<p style="font-family: Inter, sans-serif; font-size: 13px; color: {COLOURS["text_secondary"]};">'
            "Weekly average Brier score. Lower is better — the red dashed line at 0.25 is random guessing.</p>",
            unsafe_allow_html=True,
        )

        fig_brier = create_brier_trend_chart(live_data["weekly_brier"])
        st.plotly_chart(fig_brier, use_container_width=True, config={"displayModeBar": False})

        st.divider()

    # --- Section 4: CLV Tracking ---
    # CLV data comes from bet_log — currently no closing odds captured,
    # so this section shows an empty state for now
    st.markdown(
        '<div class="bv-section-header">Closing Line Value (CLV)</div>',
        unsafe_allow_html=True,
    )

    with get_session() as session:
        clv_count = session.query(BetLog).filter(
            BetLog.clv.isnot(None),
            BetLog.status.in_(["won", "lost"]),
        ).count()

    if clv_count > 0:
        with get_session() as session:
            clv_rows = (
                session.query(BetLog.date, BetLog.clv)
                .filter(
                    BetLog.clv.isnot(None),
                    BetLog.status.in_(["won", "lost"]),
                )
                .order_by(BetLog.date.asc())
                .all()
            )

        clv_df = pd.DataFrame([{"date": r.date, "clv": r.clv} for r in clv_rows])
        # Rolling average CLV (20-bet window)
        clv_df["rolling_clv"] = clv_df["clv"].rolling(window=20, min_periods=5).mean()

        fig_clv = go.Figure()
        fig_clv.add_trace(go.Scatter(
            x=clv_df["date"],
            y=clv_df["rolling_clv"],
            mode="lines",
            line=dict(color=COLOURS["green"], width=2),
            hovertemplate="Date: %{x}<br>CLV: %{y:.4f}<extra></extra>",
        ))
        fig_clv.add_hline(
            y=0, line_dash="dash",
            line_color=COLOURS["border"], line_width=1,
        )
        fig_clv.update_layout(
            title="",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="JetBrains Mono, monospace", color=COLOURS["text_secondary"], size=12),
            xaxis=dict(gridcolor=COLOURS["border"], showgrid=True, title=""),
            yaxis=dict(gridcolor=COLOURS["border"], showgrid=True, title="Rolling CLV"),
            margin=dict(l=60, r=20, t=10, b=40),
            height=300,
            showlegend=False,
        )
        st.plotly_chart(fig_clv, use_container_width=True, config={"displayModeBar": False})
    else:
        st.markdown(
            '<div class="bv-empty-state">'
            "CLV tracking requires closing odds data. This will populate automatically "
            "once the midday pipeline captures closing odds before kickoff."
            "</div>",
            unsafe_allow_html=True,
        )

    st.divider()

else:
    # No predictions at all
    st.markdown(
        '<div class="bv-empty-state">'
        "No resolved predictions yet. Run the pipeline to generate predictions, "
        "then check back after matches are finished."
        "</div>",
        unsafe_allow_html=True,
    )


# --- Section 5: Model Comparison ---
if not model_comparison.empty and len(model_comparison) >= 2:
    st.markdown(
        '<div class="bv-section-header">Model Comparison</div>',
        unsafe_allow_html=True,
    )

    # Format numeric columns
    display_df = model_comparison.copy()
    for col in ["Brier Score", "ROI %", "Avg CLV", "1X2 Win %", "O/U Win %", "BTTS Win %"]:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(
                lambda x: f"{x:.4f}" if x is not None else "—"
            )

    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.divider()

elif not model_comparison.empty and len(model_comparison) == 1:
    # Single model — show a note instead of empty
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 13px; color: {COLOURS["text_secondary"]}; '
        f'padding: 8px 0;">'
        f'Currently running a single model: <span style="color: {COLOURS["blue"]};">'
        f'{model_comparison.iloc[0]["Model"]}</span>. '
        "Model comparison will appear when additional models are added.</p>",
        unsafe_allow_html=True,
    )
    st.divider()


# --- Section 6: Ensemble Weights ---
st.markdown(
    '<div class="bv-section-header">Ensemble Weights</div>',
    unsafe_allow_html=True,
)

if ensemble_weights:
    fig_weights = create_ensemble_weights_chart(ensemble_weights)
    st.plotly_chart(fig_weights, use_container_width=True, config={"displayModeBar": False})
else:
    st.markdown(
        '<div class="bv-empty-state">'
        "Ensemble weighting activates when 2+ models are active with 300+ resolved predictions each. "
        "Currently running a single model."
        "</div>",
        unsafe_allow_html=True,
    )

st.divider()


# --- Section 7: Feature Importance ---
st.markdown(
    '<div class="bv-section-header">Feature Importance</div>',
    unsafe_allow_html=True,
)

if not feature_importance.empty:
    fig_fi = create_feature_importance_chart(feature_importance)
    st.plotly_chart(fig_fi, use_container_width=True, config={"displayModeBar": False})
else:
    st.markdown(
        '<div class="bv-empty-state">'
        "Feature importance tracking begins when a gradient boosting model "
        "(XGBoost or LightGBM) is trained. Currently using Poisson regression."
        "</div>",
        unsafe_allow_html=True,
    )

st.divider()


# --- Section 8: Market Edge Map ---
st.markdown(
    '<div class="bv-section-header">Market Edge Map</div>',
    unsafe_allow_html=True,
)

if not market_edge.empty:
    st.markdown(
        f'<p style="font-family: Inter, sans-serif; font-size: 13px; color: {COLOURS["text_secondary"]};">'
        "League × market performance heatmap. Green = profitable, yellow = promising, "
        "grey = insufficient data, red = unprofitable.</p>",
        unsafe_allow_html=True,
    )
    fig_edge = create_market_edge_heatmap(market_edge)
    st.plotly_chart(fig_edge, use_container_width=True, config={"displayModeBar": False})
else:
    st.markdown(
        '<div class="bv-empty-state">'
        "Market edge analysis requires 50+ resolved value bets per league/market combination. "
        "This populates automatically as part of the weekly summary pipeline."
        "</div>",
        unsafe_allow_html=True,
    )

st.divider()


# --- Section 9: Recalibration History ---
st.markdown(
    '<div class="bv-section-header">Recalibration History</div>',
    unsafe_allow_html=True,
)

if not cal_history.empty:
    st.dataframe(cal_history, use_container_width=True, hide_index=True)
else:
    st.markdown(
        '<div class="bv-empty-state">'
        "No recalibrations yet. Automatic recalibration triggers after every 200 resolved predictions "
        "if mean absolute calibration error exceeds 3 percentage points."
        "</div>",
        unsafe_allow_html=True,
    )

st.divider()


# --- Section 10: Retrain History ---
st.markdown(
    '<div class="bv-section-header">Retrain History</div>',
    unsafe_allow_html=True,
)

if not retrain_hist.empty:
    st.dataframe(retrain_hist, use_container_width=True, hide_index=True)
else:
    st.markdown(
        '<div class="bv-empty-state">'
        "No retrains yet. Automatic retraining triggers when the rolling Brier score "
        "degrades more than 15% from the model\'s all-time average."
        "</div>",
        unsafe_allow_html=True,
    )

# ============================================================================
# Glossary — explains every model health metric and concept (E27-03)
# ============================================================================
# The owner is learning (MP §12). This glossary defines statistical and ML
# concepts so anyone can understand whether the model is performing well.

st.divider()
with st.expander("Glossary — What do these stats mean?", expanded=False):
    st.markdown(
        '<style>'
        '.gloss-section { margin-bottom: 18px; }'
        '.gloss-title {'
        '  font-family: Inter, sans-serif; font-size: 14px; font-weight: 700;'
        '  color: #3FB950; text-transform: uppercase; letter-spacing: 0.5px;'
        '  margin-bottom: 8px; border-bottom: 1px solid #21262D; padding-bottom: 4px;'
        '}'
        '.gloss-row {'
        '  display: flex; gap: 8px; margin-bottom: 6px; line-height: 1.45;'
        '}'
        '.gloss-term {'
        '  font-family: "JetBrains Mono", monospace; font-size: 12px;'
        '  font-weight: 600; color: #E6EDF3; min-width: 140px; flex-shrink: 0;'
        '}'
        '.gloss-def {'
        '  font-family: Inter, sans-serif; font-size: 12px; color: #8B949E;'
        '}'
        '</style>',
        unsafe_allow_html=True,
    )

    # --- Prediction Accuracy ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Prediction Accuracy</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Brier Score</span>'
        '  <span class="gloss-def">Measures how accurate probability predictions are. '
        'Ranges from 0 (perfect) to 1 (worst). Lower = better. '
        'A coin flip scores 0.25. Anything below 0.20 is considered good. '
        'BetVector targets &lt;0.20 for match result predictions.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Active Model</span>'
        '  <span class="gloss-def">The prediction model currently generating forecasts. '
        'BetVector uses a Market-Augmented Poisson model that combines team stats '
        'with bookmaker odds to predict match outcomes.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Total Predictions</span>'
        '  <span class="gloss-def">How many matches the model has predicted. '
        'More predictions = more reliable performance metrics. '
        'Brier score is unreliable with fewer than 100 predictions.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Model Quality</span>'
        '  <span class="gloss-def">A qualitative label based on Brier score: '
        '<span style="color: #3FB950;">Good</span> (&lt;0.20), '
        '<span style="color: #D29922;">Fair</span> (0.20\u20130.25), '
        '<span style="color: #F85149;">Poor</span> (&gt;0.25).</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Walk-Forward</span>'
        '  <span class="gloss-def">A backtesting method where the model is trained on data up '
        'to date T, then tested on the next matchday (T+1). The training window advances and '
        'the process repeats. This mimics real-world usage and prevents the model from '
        '"seeing the future". BetVector uses walk-forward validation for all backtest metrics.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Calibration ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Calibration</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Calibration Plot</span>'
        '  <span class="gloss-def">Shows predicted probability vs actual win rate. '
        'A perfectly calibrated model has all points on the diagonal line \u2014 '
        'when it says 60%, events happen ~60% of the time.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Overconfident</span>'
        '  <span class="gloss-def">Points below the diagonal. The model predicts higher '
        'probabilities than reality \u2014 it\'s too sure of itself. '
        'Can lead to overvaluing certain bets.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Underconfident</span>'
        '  <span class="gloss-def">Points above the diagonal. The model predicts lower '
        'probabilities than reality \u2014 it\'s too cautious. '
        'May miss value bets it should have flagged.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Sample Size (dot)</span>'
        '  <span class="gloss-def">Larger dots = more predictions in that probability bin. '
        'Only trust calibration for bins with large samples.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- CLV ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Closing Line Value (CLV)</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">CLV</span>'
        '  <span class="gloss-def">Closing Line Value \u2014 compares the odds you bet at '
        'to the closing odds (final price before kickoff). '
        'Positive CLV means you consistently got better odds than the market settled at. '
        'This is the single best predictor of long-term profitability.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Rolling CLV</span>'
        '  <span class="gloss-def">Average CLV over a rolling window (typically 20 bets). '
        'A consistently positive rolling CLV confirms the model is beating the market.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Closing Line</span>'
        '  <span class="gloss-def">The final odds offered by bookmakers just before kickoff. '
        'Considered the most "accurate" price because it incorporates all available information.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Feature Importance ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Feature Importance</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Feature</span>'
        '  <span class="gloss-def">An input variable the model uses for prediction. '
        'Examples: rolling xG, PPDA, form, Elo rating, odds movement.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Gain</span>'
        '  <span class="gloss-def">How much a feature contributes to improving the model\'s '
        'predictions. Higher gain = more important input. Only available for gradient-boosted '
        'models (XGBoost/LightGBM), not Poisson regression.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Market Edge Map ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Market Edge Map</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #3FB950;">Profitable</span>'
        '  <span class="gloss-def">Positive ROI with 100+ bets and statistically significant '
        'confidence interval \u2014 strong evidence the model has an edge here.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #D29922;">Promising</span>'
        '  <span class="gloss-def">Positive ROI but fewer than 100 bets \u2014 '
        'early signal but not yet statistically reliable.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #8B949E;">Insufficient</span>'
        '  <span class="gloss-def">Fewer than 50 bets \u2014 not enough data '
        'to draw any conclusions about this market/league combination.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term" style="color: #F85149;">Unprofitable</span>'
        '  <span class="gloss-def">Negative ROI with 100+ bets \u2014 '
        'the model does not have an edge in this market. Consider excluding it.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # --- Self-Improvement ---
    st.markdown(
        '<div class="gloss-section">'
        '<div class="gloss-title">Self-Improvement</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Recalibration</span>'
        '  <span class="gloss-def">Adjusting the model\'s probability outputs so they '
        'better match observed win rates. Triggered automatically after 200+ resolved '
        'predictions. If the adjustment makes things worse, it\'s rolled back.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Retrain</span>'
        '  <span class="gloss-def">Re-fitting the entire model on updated data. '
        'Triggered when the rolling Brier score degrades more than 15% from its '
        'historical average. Includes automatic rollback if performance doesn\'t improve.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Rolled Back</span>'
        '  <span class="gloss-def">A recalibration or retrain that was reverted because it '
        'made the model worse. The system automatically detects and undoes harmful changes.</span>'
        '</div>'
        '<div class="gloss-row">'
        '  <span class="gloss-term">Brier Trend</span>'
        '  <span class="gloss-def">Weekly average Brier score over time. A flat or declining '
        'trend = model is stable or improving. A rising trend = model is getting less accurate '
        'and may trigger automatic retraining.</span>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
