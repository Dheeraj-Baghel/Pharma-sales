"""
dashboard.py  (Checkpoint 4) - Streamlit entry point
----------------------------------------------------
PharmaSales Insight dashboard for the SYNTHETIC (fictional) dataset.

Run from the project root:
    streamlit run src/dashboard.py

The page only DISPLAYS results. All calculations live in dashboard_data.py,
which reuses the verified Checkpoint 3 analysis (integer paise,
aggregate-before-merge). Amounts become INR text only at display time.

Optional (used by the tests): set PHARMA_DB_PATH to read a different
SQLite file instead of data/pharma_sales.db.
"""

import os
import sys
from pathlib import Path

# Make sibling modules in src/ importable however the app is launched
# (streamlit run, Streamlit's AppTest, or from another folder).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import analyze_sales as an
import dashboard_data as dd

DB_PATH = Path(os.environ.get("PHARMA_DB_PATH", an.DB_PATH))

st.set_page_config(page_title="PharmaSales Insight", page_icon="💊", layout="wide")

# Presentation only: on narrow screens (Streamlit stacks columns below 640 px)
# each recommendation's evidence table becomes a list with the label above
# its value, so long labels and values wrap at spaces instead of being
# squeezed into a narrow column and broken mid-word. Desktop is unchanged.
EVIDENCE_MOBILE_CSS = """
<style>
@media (max-width: 640px) {
  [class*="st-key-rec_"] [data-testid="stTableStyledTable"] thead { display: none; }
  [class*="st-key-rec_"] [data-testid="stTableStyledTable"],
  [class*="st-key-rec_"] [data-testid="stTableStyledTable"] tbody,
  [class*="st-key-rec_"] [data-testid="stTableStyledTable"] tr,
  [class*="st-key-rec_"] [data-testid="stTableStyledTable"] th,
  [class*="st-key-rec_"] [data-testid="stTableStyledTable"] td {
    display: block; width: 100%; box-sizing: border-box;
  }
  [class*="st-key-rec_"] [data-testid="stTableStyledTable"] tr {
    padding: 0.4rem 0; border-bottom: 1px solid rgba(128, 128, 128, 0.25);
  }
  [class*="st-key-rec_"] [data-testid="stTableStyledTable"] th,
  [class*="st-key-rec_"] [data-testid="stTableStyledTable"] td {
    border: none; padding: 0.1rem 0.5rem; text-align: left !important;
    white-space: normal; word-break: normal; overflow-wrap: normal; hyphens: none;
  }
  [class*="st-key-rec_"] [data-testid="stTableStyledTable"] th { font-size: 0.85rem; opacity: 0.8; }
}
</style>
"""
st.html(EVIDENCE_MOBILE_CSS)


# ===========================================================================
# Loading (cached; refreshes automatically if the database file changes)
# ===========================================================================
@st.cache_data(show_spinner="Loading and validating the database...")
def load_cached(path_text, modified_ns, size_bytes):
    # modified_ns and size_bytes are only part of the cache key, so a
    # regenerated database is picked up. Errors are never cached.
    return dd.load_dashboard_data(Path(path_text))


def load_or_stop():
    try:
        stat = DB_PATH.stat()
        return load_cached(str(DB_PATH), stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        error = dd.DashboardDataError("Database file not found",
                                      [f"Expected a SQLite file at: {DB_PATH}"],
                                      "From the project folder run:  python src/generate_data.py")
    except dd.DashboardDataError as caught:
        error = caught
    except OSError as caught:
        error = dd.DashboardDataError("The database file could not be read",
                                      [f"{DB_PATH}: {caught}"],
                                      "Check the file exists and you have permission to read it.")
    st.error(f"**{error.title}**\n\n" + "\n".join(f"- {d}" for d in error.details))
    st.info(f"**How to fix:** {error.recovery}")
    st.stop()      # nothing below this line runs: no KPIs, no charts


# ===========================================================================
# Small display helpers (paise -> INR happens only here)
# ===========================================================================
def inr(paise):
    return an.format_inr(paise)


def pct(value):
    return "n/a" if pd.isna(value) else f"{value:.2f}%"


def rupees(paise_series):
    """Paise -> rupees as numbers, for chart axes only."""
    return paise_series.astype("float64") / 100


def labels(months):
    return [dd.month_label(m) for m in months]


# ===========================================================================
# Sidebar filters
# ===========================================================================
data = load_or_stop()
defaults = dd.default_filters(data)
all_months = dd.unique_in_order(sorted(data["targets"]["month"]))


def reset_filters():
    st.session_state["start_month"] = defaults.start_month
    st.session_state["end_month"] = defaults.end_month
    st.session_state["regions"] = list(defaults.regions)
    st.session_state["products"] = list(defaults.products)


if "start_month" not in st.session_state:
    reset_filters()

with st.sidebar:
    st.header("Filters")
    st.caption("Whole calendar months (the plan is monthly).")
    st.selectbox("From month", options=all_months, format_func=dd.month_label, key="start_month")
    st.selectbox("To month", options=all_months, format_func=dd.month_label, key="end_month")
    st.multiselect("Regions", options=list(defaults.regions), key="regions")
    st.multiselect("Products", options=list(defaults.products), key="products")
    st.button("Reset to all of 2025", on_click=reset_filters, key="reset")
    st.caption("Filters apply equally to actual sales and to targets.")

filters = dd.Filters(st.session_state["start_month"], st.session_state["end_month"],
                     tuple(st.session_state["regions"]), tuple(st.session_state["products"]))

# ===========================================================================
# Header and scope
# ===========================================================================
st.title("PharmaSales Insight")
st.caption("⚠️ All data is **synthetic and fictional**. Figures describe this generated dataset, "
           "not any real company, product or person. The plan is flat by design, so seasonal "
           "swings partly reflect how the data was generated.")
st.markdown(f"**Active scope:** {dd.describe_scope(filters, data)}")

if filters.start_month > filters.end_month:
    st.warning(f"**'From month' ({dd.month_label(filters.start_month)}) is after 'To month' "
               f"({dd.month_label(filters.end_month)}).** Choose a From month on or before "
               "the To month, or use **Reset to all of 2025**.")
    st.stop()

view = dd.compute_view(data, filters)
if view["empty"]:
    missing = [name for name, chosen in [("region", filters.regions),
                                         ("product", filters.products)] if not chosen]
    reason = (f"Select at least one {' and one '.join(missing)}." if missing
              else "No planned month–region–product groups match these filters.")
    st.info(f"**No planned groups in this selection.** {reason} "
            "Use **Reset to all of 2025** in the sidebar to start again.")
    st.stop()

k = view["kpis"]
st.caption(f"{k['planned_groups']} planned month–region–product groups · "
           f"{k['groups_without_sales']} with no sales · {k['transactions']} transactions")

overview, regional_tab, product_tab, insights_tab = st.tabs(
    ["Executive Overview", "Regional Analysis", "Product Analysis", "Business Insights"])

# ===========================================================================
# 1. Executive Overview
# ===========================================================================
with overview:
    # Layout: the two revenue cards get a wide row of their own so long rupee
    # amounts are never clipped; the other three KPIs sit in a row below.
    c1, c2 = st.columns(2)
    c1.metric("Net revenue", inr(k["actual_paise"]))
    c2.metric("Planned net revenue", inr(k["plan_paise"]))
    c3, c4, c5 = st.columns(3)
    c3.metric("Target achievement", pct(k["achievement_pct"]))
    c4.metric("Shortfall (plan − actual)", inr(k["shortfall_paise"]))
    c5.metric("Units sold", f"{k['units_sold']:,}")
    st.caption("Achievement = 100 × total actual ÷ total plan. "
               "Positive shortfall = below plan; negative = above plan.")

    monthly = view["monthly"]
    fig = go.Figure()
    fig.add_bar(x=labels(monthly["month"]), y=rupees(monthly["actual_paise"]),
                name="Actual net revenue", hovertemplate="%{x}<br>Actual ₹%{y:,.2f}<extra></extra>")
    fig.add_scatter(x=labels(monthly["month"]), y=rupees(monthly["plan_paise"]),
                    name="Planned net revenue", mode="lines+markers",
                    hovertemplate="%{x}<br>Plan ₹%{y:,.2f}<extra></extra>")
    fig.update_layout(title="Monthly actual vs plan (INR)", yaxis_title="INR",
                      legend_orientation="h", margin=dict(t=60, b=20))
    st.plotly_chart(fig, key="monthly_chart")

    st.subheader("Month-over-month revenue change")
    growth = monthly.dropna(subset=["growth_paise"])
    if growth.empty:
        st.caption("Only one month is visible, so there is no previous month to compare.")
    else:
        colors = ["#2e7d32" if g >= 0 else "#c62828" for g in growth["growth_paise"]]
        gfig = go.Figure(go.Bar(x=labels(growth["month"]), y=rupees(growth["growth_paise"].astype("int64")),
                                marker_color=colors,
                                hovertemplate="%{x}<br>Change ₹%{y:,.2f}<extra></extra>"))
        gfig.update_layout(title="Change vs previous visible month (INR)", yaxis_title="INR",
                           margin=dict(t=60, b=20))
        st.plotly_chart(gfig, key="growth_chart")
    st.dataframe(pd.DataFrame({
        "Month": labels(monthly["month"]),
        "Actual": monthly["actual_paise"].map(inr),
        "Plan": monthly["plan_paise"].map(inr),
        "Achievement": monthly["achievement_pct"].map(pct),
        "Change (INR)": monthly["growth_paise"].map(inr),
        "Change (%)": monthly["growth_pct"].map(pct),
    }), hide_index=True, width="stretch", key="monthly_table")
    st.caption("The first visible month has no change (n/a). After a ₹0 month the INR change "
               "is shown but the percentage is n/a.")

# ===========================================================================
# 2. Regional Analysis
# ===========================================================================
with regional_tab:
    regional = view["regional"].sort_values("achievement_pct")
    rfig = go.Figure()
    rfig.add_bar(x=regional["region"], y=rupees(regional["actual_paise"]), name="Actual",
                 hovertemplate="%{x}<br>Actual ₹%{y:,.2f}<extra></extra>")
    rfig.add_bar(x=regional["region"], y=rupees(regional["plan_paise"]), name="Plan",
                 hovertemplate="%{x}<br>Plan ₹%{y:,.2f}<extra></extra>")
    rfig.update_layout(title="Actual vs plan by region (lowest achievement first)",
                       barmode="group", yaxis_title="INR", legend_orientation="h",
                       margin=dict(t=60, b=20))
    st.plotly_chart(rfig, key="region_chart")
    st.dataframe(pd.DataFrame({
        "Region": regional["region"],
        "Net revenue": regional["actual_paise"].map(inr),
        "Share of selected revenue": regional["share_pct"].map(pct),
        "Plan": regional["plan_paise"].map(inr),
        "Achievement": regional["achievement_pct"].map(pct),
        "Shortfall": regional["shortfall_paise"].map(inr),
        "Status": regional["status"],
    }), hide_index=True, width="stretch", key="region_table")

# ===========================================================================
# 3. Product Analysis
# ===========================================================================
with product_tab:
    product = view["product"].sort_values("actual_paise", ascending=False)
    pfig = go.Figure(go.Bar(
        y=product["product"], x=product["achievement_pct"].fillna(0), orientation="h",
        marker_color=["#c62828" if s > 0 else "#2e7d32" for s in product["shortfall_paise"]],
        hovertemplate="%{y}<br>Achievement %{x:.2f}%<extra></extra>"))
    pfig.add_vline(x=100, line_dash="dash", annotation_text="Plan (100%)")
    pfig.update_layout(title="Target achievement by product (red = below plan)",
                       xaxis_title="Achievement %", margin=dict(t=60, b=20))
    st.plotly_chart(pfig, key="product_chart")
    st.dataframe(pd.DataFrame({
        "Product": product["product"],
        "Net revenue": product["actual_paise"].map(inr),
        "Units sold": product["units_sold"],
        "Avg discount (simple avg per transaction)": product["avg_discount_pct"].map(pct),
        "Plan": product["plan_paise"].map(inr),
        "Achievement": product["achievement_pct"].map(pct),
        "Shortfall": product["shortfall_paise"].map(inr),
    }), hide_index=True, width="stretch", key="product_table")
    st.caption("Average discount is a simple (unweighted) average across transactions; "
               "n/a where a product had no sales in this scope.")

# ===========================================================================
# 4. Business Insights (findings + data-backed recommendations)
# ===========================================================================
with insights_tab:
    st.markdown("Descriptive findings for the **active filters**.")
    for line in dd.build_insights(view):
        st.markdown(f"- {line}")

    # Recommendations are recomputed from the same filtered view on every rerun.
    st.subheader("Recommendations")
    st.caption(f"Up to {dd.MAX_RECOMMENDATIONS} suggestions from simple rules applied to the "
               f"active selection. {dd.SEASONALITY_NOTE}")
    recommendations = dd.build_recommendations(view)
    if not recommendations:
        st.info("No recommendation rule applies to this selection.")
    for number, rec in enumerate(recommendations, start=1):
        with st.container(border=True, key=f"rec_{rec.rule}"):
            st.markdown(f"**{number}. {rec.title}**")
            st.markdown(f"**Finding:** {rec.finding}")
            # A small static table keeps the supporting numbers visible at a glance.
            st.table(pd.DataFrame(rec.evidence, columns=["Evidence", "Value"])
                     .set_index("Evidence"))
            st.markdown(f"**Suggested next step:** {rec.next_step}")
    gaps = dd.top_monthly_gaps(view)
    if not gaps.empty:
        st.subheader("Largest monthly gaps in scope")
        st.dataframe(pd.DataFrame({
            "Month": labels(gaps["month"]),
            "Region": gaps["region"],
            "Product": gaps["product"],
            "Transactions": gaps["transaction_count"],
            "Actual": gaps["actual_paise"].map(inr),
            "Plan": gaps["target_paise"].map(inr),
            "Shortfall": gaps["shortfall_paise"].map(inr),
        }), hide_index=True, width="stretch", key="gaps_table")
    st.caption("All findings describe a synthetic dataset.")
