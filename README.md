import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, date
from dateutil import parser
import requests

# -----------------------------
# CONFIG – ADJUST THESE IF NEEDED
# -----------------------------


DEFAULT_SCALP_SEC = 180        # <= 180 seconds = scalping
DEFAULT_HFT_HOLD_SEC = 60      # avg holding <= 60 sec
DEFAULT_HFT_TRADES_PER_MIN = 5 # >= 5 trades in any minute
DEFAULT_ARB_HOLD_SEC = 10      # <= 10 sec trades
DEFAULT_ARB_WINRATE = 0.8      # 80% winrate in ultra-short trades

# Expected column names from MT5 CSV.
# If your CSV headers differ, change these.
COL_TICKET = "Ticket"
COL_LOGIN = "Login"
COL_OPEN_TIME = "Open Time"
COL_CLOSE_TIME = "Close Time"
COL_SYMBOL = "Symbol"
COL_VOLUME = "Volume"
COL_PROFIT = "Profit"
COL_TYPE = "Type"  # Buy/Sell etc.


# -----------------------------
# HELPER FUNCTIONS
# -----------------------------


def parse_datetime_col(df: pd.DataFrame, col_name: str) -> pd.Series:
    """Parse a datetime column safely."""
    return pd.to_datetime(df[col_name], errors="coerce")


def detect_toxic_trades(
    df: pd.DataFrame,
    scalp_sec: int = DEFAULT_SCALP_SEC,
    hft_hold_sec: int = DEFAULT_HFT_HOLD_SEC,
    hft_trades_per_min: int = DEFAULT_HFT_TRADES_PER_MIN,
    arb_hold_sec: int = DEFAULT_ARB_HOLD_SEC,
    arb_winrate_threshold: float = DEFAULT_ARB_WINRATE,
):
    """
    Core logic:
    - Calculate holding_sec
    - Classify scalping, HFT-suspect, arbitrage-suspect
    - Build summary metrics
    """

    # Ensure datetime columns
    df[COL_OPEN_TIME] = parse_datetime_col(df, COL_OPEN_TIME)
    df[COL_CLOSE_TIME] = parse_datetime_col(df, COL_CLOSE_TIME)

    # Drop trades without proper times
    df = df.dropna(subset=[COL_OPEN_TIME, COL_CLOSE_TIME]).copy()

    # Holding time
    df["holding_sec"] = (df[COL_CLOSE_TIME] - df[COL_OPEN_TIME]).dt.total_seconds()

    # Scalping trades
    df["is_scalp"] = df["holding_sec"] <= scalp_sec

    # Per-minute trades (for HFT)
    df["open_minute"] = df[COL_OPEN_TIME].dt.floor("min")
    trades_per_minute = df.groupby("open_minute")[COL_TICKET].count()
    max_trades_per_minute = trades_per_minute.max() if not trades_per_minute.empty else 0

    avg_holding_sec = df["holding_sec"].mean() if len(df) > 0 else 0

    # HFT suspicion
    is_hft_suspect = bool(
        (avg_holding_sec <= hft_hold_sec) and (max_trades_per_minute >= hft_trades_per_min)
    )

    # Arbitrage suspicion: look at ultra-short trades
    short_df = df[df["holding_sec"] <= arb_hold_sec]
    arb_suspect = False
    arb_winrate = None
    arb_trades_count = len(short_df)

    if arb_trades_count > 0:
        arb_winrate = (short_df[COL_PROFIT] > 0).mean()
        arb_suspect = bool(arb_winrate >= arb_winrate_threshold)

    # Label flags per trade for UI filtering
    df["is_hft_time_band"] = df["holding_sec"] <= hft_hold_sec
    df["is_arb_short"] = df["holding_sec"] <= arb_hold_sec

    # Basic P&L
    total_trades = len(df)
    total_profit = df[COL_PROFIT].sum() if COL_PROFIT in df.columns else 0.0
    scalping_trades = df["is_scalp"].sum()
    scalping_profit = df.loc[df["is_scalp"], COL_PROFIT].sum() if COL_PROFIT in df.columns else 0.0

    # ToxicScore (simple example)
    scalp_index = scalping_trades / total_trades if total_trades > 0 else 0
    hft_index = 1.0 if is_hft_suspect else 0.0
    arb_index = arb_winrate if arb_winrate is not None else 0.0

    # You can tune these weights
    w1, w2, w3 = 0.4, 0.3, 0.3
    toxic_score = (w1 * scalp_index + w2 * hft_index + w3 * arb_index) * 100

    summary = {
        "total_trades": int(total_trades),
        "total_profit": float(total_profit),
        "scalping_trades": int(scalping_trades),
        "scalping_trades_pct": float(scalp_index * 100 if total_trades > 0 else 0),
        "scalping_profit": float(scalping_profit),
        "avg_holding_sec": float(avg_holding_sec),
        "max_trades_per_minute": int(max_trades_per_minute),
        "is_hft_suspect": is_hft_suspect,
        "arb_trades_count": int(arb_trades_count),
        "arb_winrate": float(arb_winrate * 100) if arb_winrate is not None else None,
        "arb_suspect": arb_suspect,
        "toxic_score": float(toxic_score),
    }

    return df, summary


def build_equity_curve(df: pd.DataFrame):
    """Cumulative P&L over time."""
    if COL_PROFIT not in df.columns:
        return None

    ec = df.sort_values(COL_CLOSE_TIME).copy()
    ec["cum_pnl"] = ec[COL_PROFIT].cumsum()
    return ec[[COL_CLOSE_TIME, "cum_pnl"]]


# -----------------------------
# STREAMLIT UI
# -----------------------------


def show_summary_cards(summary: dict):
    """Display key metrics at the top."""
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Trades", summary["total_trades"])
    col1.metric("Total Profit", f"{summary['total_profit']:.2f}")

    col2.metric("Scalping Trades", summary["scalping_trades"])
    col2.metric("Scalping %", f"{summary['scalping_trades_pct']:.1f}%")

    arb_label = "Yes" if summary["arb_suspect"] else "No"
    arb_winrate_str = (
        f"{summary['arb_winrate']:.1f}%"
        if summary["arb_winrate"] is not None
        else "N/A"
    )

    col3.metric("HFT Suspect", "Yes" if summary["is_hft_suspect"] else "No")
    col3.metric("Arb Suspect / Winrate", f"{arb_label} / {arb_winrate_str}")


def show_toxic_score(summary: dict):
    score = summary["toxic_score"]
    if score >= 70:
        level = "High risk"
    elif score >= 40:
        level = "Medium risk"
    else:
        level = "Low risk"

    st.subheader("Toxic Trading Score")
    st.write(
        f"**Score:** {score:.1f} / 100  →  **{level}**\n\n"
        "- This is a simple combined score from scalping %, HFT pattern and arbitrage-like behavior.\n"
        "- You can later adjust the formula/weights in code as per dealing team feedback."
    )


def show_charts(df: pd.DataFrame):
    st.subheader("Equity Curve (Cumulative P&L)")
    equity_df = build_equity_curve(df)
    if equity_df is not None and not equity_df.empty:
        fig_ec = px.line(
            equity_df,
            x=COL_CLOSE_TIME,
            y="cum_pnl",
            labels={COL_CLOSE_TIME: "Close Time", "cum_pnl": "Cumulative P&L"},
        )
        st.plotly_chart(fig_ec, use_container_width=True)
    else:
        st.info("No profit column available to build equity curve.")

    st.subheader("Holding Time Distribution (seconds)")
    fig_h = px.histogram(
        df,
        x="holding_sec",
        nbins=50,
        labels={"holding_sec": "Holding time (sec)"},
    )
    st.plotly_chart(fig_h, use_container_width=True)

    st.subheader("Trades per Minute")
    per_min = df.groupby("open_minute")[COL_TICKET].count().reset_index()
    per_min.rename(columns={COL_TICKET: "trades"}, inplace=True)
    if not per_min.empty:
        fig_tm = px.bar(
            per_min,
            x="open_minute",
            y="trades",
            labels={"open_minute": "Time (minute)", "trades": "Trades"},
        )
        st.plotly_chart(fig_tm, use_container_width=True)


def show_trade_table(df: pd.DataFrame):
    st.subheader("Trade Details with Flags")

    # Quick filters
    show_scalp = st.checkbox("Show only scalping trades (<= 180 sec)", value=False)
    show_hft = st.checkbox("Show only HFT-time-band trades (<= 60 sec)", value=False)
    show_arb = st.checkbox("Show only arbitrage-short trades (<= 10 sec)", value=False)

    filtered = df.copy()
    if show_scalp:
        filtered = filtered[filtered["is_scalp"]]
    if show_hft:
        filtered = filtered[filtered["is_hft_time_band"]]
    if show_arb:
        filtered = filtered[filtered["is_arb_short"]]

    st.dataframe(
        filtered[
            [
                COL_TICKET,
                COL_SYMBOL,
                COL_VOLUME,
                COL_OPEN_TIME,
                COL_CLOSE_TIME,
                "holding_sec",
                COL_PROFIT,
                "is_scalp",
                "is_hft_time_band",
                "is_arb_short",
            ]
        ],
        use_container_width=True,
    )

    # Download option
    csv = filtered.to_csv(index=False).encode("utf-8")
    st.download_button("Download filtered trades as CSV", data=csv, file_name="toxic_trades_filtered.csv")


def fetch_trades_from_api(api_url: str, manager_login: str, manager_password: str,
                          account_login: str, from_dt: datetime, to_dt: datetime) -> pd.DataFrame:
    """
    This is a placeholder for your MT5 Manager connector API.
    You (or your dev) should implement the actual endpoint on the MT5 side.

    Expected API format (example, you can change):
      GET {api_url}/trades
        params:
          manager_login, manager_password, account_login, from, to

    Response expected:
      JSON list of trades with fields matching the columns we use.
    """
    params = {
        "manager_login": manager_login,
        "manager_password": manager_password,
        "account_login": account_login,
        "from": from_dt.isoformat(),
        "to": to_dt.isoformat(),
    }

    resp = requests.get(f"{api_url.rstrip('/')}/trades", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    df = pd.DataFrame(data)
    return df


def main():
    st.set_page_config(page_title="MT5 Toxic Trading Analyzer", layout="wide")
    st.title("MT5 Toxic Trading Analyzer (Cloud)")

    st.markdown(
        """
        Use this tool to analyze **toxic trading behavior** on MT5 accounts:
        - Scalping (holding time <= 180s)  
        - HFT-style patterns (very short holding time + many trades per minute)  
        - Arbitrage-like behavior (ultra-short trades with high winrate)  
        """
    )

    mode = st.radio(
        "Choose data source:",
        ["Upload MT5 CSV (Deals History)", "Fetch via API (MT5 Manager connector)"],
        help="Start with CSV upload. Later you can connect directly to MT5 via your own HTTP API.",
    )

    if mode == "Upload MT5 CSV (Deals History)":
        st.subheader("1. Upload MT5 deals report CSV")
        uploaded_file = st.file_uploader(
            "Upload CSV exported from MT5 Manager (Deals report for one account)",
            type=["csv"],
        )

        if uploaded_file is not None:
            try:
                df_raw = pd.read_csv(uploaded_file)
            except Exception:
                uploaded_file.seek(0)
                df_raw = pd.read_csv(uploaded_file, sep=";")

            st.write("Preview of uploaded data:")
            st.dataframe(df_raw.head(), use_container_width=True)

            if st.button("Run Toxic Analysis"):
                df, summary = detect_toxic_trades(df_raw)
                show_summary_cards(summary)
                show_toxic_score(summary)
                show_charts(df)
                show_trade_table(df)

    else:
        st.subheader("1. API Connection Settings")

        with st.form("api_form"):
            api_url = st.text_input(
                "MT5 Connector API URL",
                value="https://your-mt5-connector.yourdomain.com",
                help="This is the HTTP endpoint your developer will expose near MT5 Manager."
            )
            manager_login = st.text_input("Manager Login", type="default")
            manager_password = st.text_input("Manager Password", type="password")
            account_login = st.text_input("MT5 Account Login", type="default")

            col_from, col_to = st.columns(2)
            from_date = col_from.date_input("From Date", value=date.today())
            to_date = col_to.date_input("To Date", value=date.today())

            submitted = st.form_submit_button("Fetch and Analyze")

        if submitted:
            if not all([api_url, manager_login, manager_password, account_login]):
                st.error("Please fill all API + account details.")
            else:
                with st.spinner("Fetching trades from API..."):
                    try:
                        from_dt = datetime.combine(from_date, datetime.min.time())
                        to_dt = datetime.combine(to_date, datetime.max.time())
                        df_raw = fetch_trades_from_api(
                            api_url,
                            manager_login,
                            manager_password,
                            account_login,
                            from_dt,
                            to_dt,
                        )
                    except Exception as e:
                        st.error(f"Error while calling API: {e}")
                        return

                st.write("Preview of data returned from API:")
                st.dataframe(df_raw.head(), use_container_width=True)

                df, summary = detect_toxic_trades(df_raw)
                show_summary_cards(summary)
                show_toxic_score(summary)
                show_charts(df)
                show_trade_table(df)


if __name__ == "__main__":
    main()
