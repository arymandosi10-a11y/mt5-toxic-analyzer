import streamlit as st
import pandas as pd
import plotly.express as px

# ---------------------------
# CONFIG
# ---------------------------
SCALPING_SECONDS = 180          # <= 180s = scalping
HFT_HOLDING_SECONDS = 60        # Avg holding <= 60s
HFT_TRADES_PER_MIN = 5          # >= 5 trades in any minute
ARBITRAGE_SECONDS = 10          # <= 10s
ARBITRAGE_WINRATE = 0.80        # 80% winrate on ultra-short trades

st.set_page_config(
    page_title="MT5 Toxic Trading Analyzer",
    layout="wide"
)

st.title("MT5 Toxic Trading Analyzer")
st.write(
    """
    Analyze MT5 trading behavior for:

    - Scalping  
    - HFT trading  
    - Arbitrage / Toxic activity  
    """
)

# ---------------------------
# FILE UPLOAD (CSV + XLSX)
# ---------------------------
uploaded_file = st.file_uploader(
    "Upload MT5 Deals / Trading History (CSV or Excel)",
    type=["csv", "xlsx"]
)

df = None

if uploaded_file is not None:
    filename = uploaded_file.name.lower()

    try:
        if filename.endswith(".xlsx"):
            # Excel file (needs openpyxl installed on the server)
            df = pd.read_excel(uploaded_file)
        else:
            # CSV file
            try:
                df = pd.read_csv(uploaded_file)
            except Exception:
                # Some MT5 exports use ';' as separator
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, sep=";")
    except Exception as e:
        st.error(f"Error reading file: {e}")
        df = None

if df is not None:
    st.subheader("Uploaded Data Preview")
    st.dataframe(df.head(), use_container_width=True)

    # ---------------------------
    # REQUIRED COLUMNS CHECK
    # ---------------------------
    required_cols = [
        "Ticket",
        "Open Time",
        "Close Time",
        "Symbol",
        "Volume",
        "Profit",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        st.error(f"Missing required columns: {missing}")
        st.stop()

    # ---------------------------
    # PROCESS DATA
    # ---------------------------
    df["Open Time"] = pd.to_datetime(df["Open Time"], errors="coerce")
    df["Close Time"] = pd.to_datetime(df["Close Time"], errors="coerce")

    df = df.dropna(subset=["Open Time", "Close Time"])

    df["Holding Seconds"] = (
        df["Close Time"] - df["Open Time"]
    ).dt.total_seconds()

    df["Scalping"] = df["Holding Seconds"] <= SCALPING_SECONDS
    df["HFT_Band"] = df["Holding Seconds"] <= HFT_HOLDING_SECONDS
    df["Arbitrage_Short"] = df["Holding Seconds"] <= ARBITRAGE_SECONDS

    # Trades per minute (for HFT detection)
    df["Open Minute"] = df["Open Time"].dt.floor("min")
    trades_per_min = df.groupby("Open Minute")["Ticket"].count()
    max_trades_per_min = trades_per_min.max() if not trades_per_min.empty else 0

    avg_holding = df["Holding Seconds"].mean() if len(df) > 0 else 0
    hft_suspect = (
        avg_holding <= HFT_HOLDING_SECONDS
        and max_trades_per_min >= HFT_TRADES_PER_MIN
    )

    # Arbitrage suspicion: ultra short trades
    arb_df = df[df["Arbitrage_Short"]]
    arb_winrate = None
    arb_suspect = False

    if len(arb_df) > 0:
        arb_winrate = (arb_df["Profit"] > 0).mean()
        arb_suspect = arb_winrate >= ARBITRAGE_WINRATE

    # ---------------------------
    # SUMMARY
    # ---------------------------
    total_trades = len(df)
    total_profit = df["Profit"].sum()

    scalp_trades = df["Scalping"].sum()
    scalp_profit = df.loc[df["Scalping"], "Profit"].sum()

    # Simple toxic score (you can tune later)
    toxic_score = (
        (scalp_trades / total_trades if total_trades else 0) * 40
        + (30 if hft_suspect else 0)
        + ((arb_winrate or 0) * 30)
    )

    st.divider()
    st.subheader("Summary")

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Trades", total_trades)
    c1.metric("Total P&L", round(total_profit, 2))

    c2.metric("Scalping Trades", scalp_trades)
    c2.metric("Scalping P&L", round(scalp_profit, 2))

    c3.metric("HFT Suspect", "YES" if hft_suspect else "NO")
    c3.metric(
        "Arbitrage Winrate",
        f"{arb_winrate:.1%}" if arb_winrate is not None else "N/A"
    )

    risk_level = (
        "HIGH RISK" if toxic_score >= 70
        else "MEDIUM RISK" if toxic_score >= 40
        else "LOW RISK"
    )

    st.subheader(f"Toxic Score: {round(toxic_score, 1)} / 100 → {risk_level}")

    # ---------------------------
    # EQUITY CURVE
    # ---------------------------
    st.divider()
    st.subheader("Equity Curve")

    df_sorted = df.sort_values("Close Time")
    df_sorted["Cumulative P&L"] = df_sorted["Profit"].cumsum()

    fig_eq = px.line(
        df_sorted,
        x="Close Time",
        y="Cumulative P&L",
        title="Cumulative P&L Over Time",
    )
    st.plotly_chart(fig_eq, use_container_width=True)

    # ---------------------------
    # HOLDING TIME DISTRIBUTION
    # ---------------------------
    st.subheader("Holding Time Distribution (Seconds)")
    fig_hold = px.histogram(
        df,
        x="Holding Seconds",
        nbins=50,
        title="Distribution of Holding Time",
    )
    st.plotly_chart(fig_hold, use_container_width=True)

    # ---------------------------
    # TRADES TABLE WITH FILTERS
    # ---------------------------
    st.divider()
    st.subheader("Trades Analysis Table")

    only_scalp = st.checkbox("Show only Scalping trades (<= 180 sec)")
    only_hft = st.checkbox("Show only HFT time-band trades (<= 60 sec)")
    only_arb = st.checkbox("Show only Arbitrage-short trades (<= 10 sec)")

    view_df = df.copy()

    if only_scalp:
        view_df = view_df[view_df["Scalping"]]
    if only_hft:
        view_df = view_df[view_df["HFT_Band"]]
    if only_arb:
        view_df = view_df[view_df["Arbitrage_Short"]]

    st.dataframe(
        view_df[
            [
                "Ticket",
                "Symbol",
                "Volume",
                "Open Time",
                "Close Time",
                "Holding Seconds",
                "Profit",
                "Scalping",
                "HFT_Band",
                "Arbitrage_Short",
            ]
        ],
        use_container_width=True,
    )

    csv_out = view_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Filtered Trades CSV",
        csv_out,
        "filtered_trades.csv",
    )
else:
    st.info("Please upload an MT5 deals / history file to start the analysis.")
