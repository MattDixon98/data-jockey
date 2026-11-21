"""Top-pick ROI over time: 1 unit per race at SP on our favourite vs the
market's, from the REST API's daily scorecard rows (period_type=day).

  streamlit run app.py

DATA_JOCKEY_API_URL picks the API (default: the live site).
"""

import os

import pandas as pd
import requests
import streamlit as st

API_URL = os.environ.get("DATA_JOCKEY_API_URL", "https://mattdixon.uk/api/v1").rstrip("/")
# The snapshot is rebuilt once a day and fetched every 15 min; no need to ask more often.
CACHE_SECONDS = 15 * 60
LINES = {
  "top_pick_roi_model": "Our favourite",
  "top_pick_roi_market": "Market favourite",
}
VIEWS = {
  "after_race": "After the race (market = SP)",
  "site_pick": "Race morning (market = forecast)",
}


@st.cache_data(ttl=CACHE_SECONDS)
def daily_rows(view: str) -> pd.DataFrame:
  response = requests.get(
    f"{API_URL}/scorecard/",
    params={"view": view, "period_type": "day"},
    timeout=30,
  )
  response.raise_for_status()
  return pd.DataFrame(response.json())


def roi_by_day(rows: pd.DataFrame, cumulative: bool) -> pd.DataFrame:
  """One row per day, one column per line, ROI in %. Cumulative = total profit
  so far / races so far (each strategy stakes 1 unit per race)."""
  rows = rows.assign(day=pd.to_datetime(rows["period"])).sort_values("day").set_index("day")
  if not cumulative:
    roi = rows[list(LINES)]
  else:
    races = rows["races"].cumsum()
    roi = pd.DataFrame({
      line: rows[line.replace("_roi_", "_profit_")].cumsum() / races
      for line in LINES
    })
  return (roi * 100).rename(columns=LINES)


st.set_page_config(page_title="Top-pick ROI", page_icon="📈")
st.title("Top-pick ROI over time")
st.caption(
  "1 unit per race at SP on our favourite vs the market's favourite, out-of-sample races only. "
  "Joint favourites split the unit."
)

view = st.radio("View", list(VIEWS), format_func=VIEWS.get, horizontal=True)
rows = daily_rows(view)
if rows.empty:
  st.info("No daily scorecard rows yet.")
  st.stop()

groups = sorted(rows["race_group"].unique(), key=lambda g: (g != "all", g))
race_group = st.radio("Races", groups, horizontal=True)
cumulative = st.toggle("Cumulative", value=True, help="Off: each day's ROI on its own (a few races, so noisy).")

rows = rows[rows["race_group"] == race_group]
chart = roi_by_day(rows, cumulative)
st.line_chart(chart, y_label="ROI (%)", x_label="Race day")

latest = chart.iloc[-1]
first, second = st.columns(2)
label = "to date" if cumulative else f"on {chart.index[-1]:%d %b}"
first.metric(f"Our favourite, {label}", f"{latest['Our favourite']:+.1f}%")
second.metric(f"Market favourite, {label}", f"{latest['Market favourite']:+.1f}%")
st.caption(f"{int(rows['races'].sum())} races, {len(rows)} race days. Data: {API_URL}/scorecard/?period_type=day")
