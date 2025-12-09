import streamlit as st
import pandas as pd
import plotly.express as px

# ---------------------------
# CONFIG
# ---------------------------
SCALPING_SECONDS = 180
HFT_HOLDING_SECONDS = 60
HFT_TRADES_PER_MIN = 5
ARBITRAGE_SECONDS = 10
ARBITRAGE_WINRATE = 0.80

st.set_page_config(page_title="MT5 Toxic Trading Analyzer", layout="wide")
st.title("MT5 Toxic Trading Analyzer")

st.write("""
Analyze MT5 trading behavior for:
- Scalping
- HFT trading
- Arbitrage / Toxic activity
""")

# ---------------------------
# HELPER: FIND REAL HEADER
# ---------------------------
def normalize_col(col):
    return str(col).strip().lower().replace(" ", "")

def detect_mt5_table(df_raw):
    required = ["ticket", "opentime", "closetime", "symbol", "volume", "profit"]

    for i in range(len(df_raw)):
        row = df_raw.iloc[i].astype(str)
        norm = [normalize_col(c) for c in row]
        if all(r in norm for r in required):
            df = df_raw.iloc[i + 1 :].copy()
            df.columns = row
            return df

    return None

# ---------------------------
# FILE UPLOAD
# ---------------------------
uploaded_file = st.file_uploader(
    "Upload MT5 Deals / Trading History (CSV or Excel)",
    type=["csv", "xlsx"]
)

df = None

if uploaded_file:
    try:
        if uploaded_file.name.lower().endswith(".xlsx"):
            raw = pd.read_excel(uploaded_file, header=None)
        else:
            raw = pd.read_csv(uploaded_file, header=None)

        df = detect_mt5_table(raw)

        if df is None:
            st.error("❌ Could not detect MT5 trade table header.")
            st.stop()

    except Exception as e:
        st.error(f"File read error: {e}")
        st.stop()

# ---------------------------
# PROCESS DATA
# ---------------------------
if df is not None:
    st.subheader("Detected Trade Table Preview")
    st.dataframe(df.head(), use_container_width=True)

    # Normalize column names
    df.columns = [normalize_col(c) for c in df.columns]

    col_map = {
        "ticket": "Ticket",
        "opentime": "Open Time",
        "closetime": "Close Time",
        "symbol": "Symbol",
        "volume": "Volume",
        "profit": "Profit",
    }

    df = df.rename(columns=col_map)

    required_cols = list(col_map.values())
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        st.error(f"Missing required columns: {missing}")
        st.stop()

    df["Open Time"] = pd.to_datetime(df["Open Time"], errors="coerce")
    df["Close Time"] = pd.to_datetime(df["Close Time"], errors="coerce")
    df = df.dropna(subset=["Open Time", "Close Time"])

    df["Profit"] = pd.to_numeric(df["Profit"], errors="coerce").fillna(0)
    df["Volume"] = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)

    df["Holding Seconds"] = (df["Close Time"] - df["Open Time"]).dt.total_seconds()

    df["Scalping"] = df["Holding Seconds"] <= SCALPING_SECONDS
    df["HFT"] = df["Holding Seconds"] <= HFT_HOLDING_SECONDS
    df["Arbitrage"] = df["Holding Seconds"] <= ARBITRAGE_SECONDS

    # ---------------------------
    # METRICS
    # ---------------------------
    total_trades = len(df)
    total_profit = df["Profit"].sum()

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Trades", total_trades)
    c2.metric("Total P&L", round(total_profit, 2))
    c3.metric("Scalping Trades", df["Scalping"].sum())

    # ---------------------------
    # EQUITY CURVE
    # ---------------------------
    st.subheader("Equity Curve")
    df_sorted = df.sort_values("Close Time")
    df_sorted["Cumulative P&L"] = df_sorted["Profit"].cumsum()

    fig = px.line(
        df_sorted,
        x="Close Time",
        y="Cumulative P&L",
        title="Cumulative Profit/Loss"
    )
    st.plotly_chart(fig, use_container_width=True)

    # ---------------------------
    # TABLE
    # ---------------------------
    st.subheader("Trade Details")
    st.dataframe(
        df[
            [
                "Ticket",
                "Symbol",
                "Volume",
                "Open Time",
                "Close Time",
                "Holding Seconds",
                "Profit",
                "Scalping",
                "HFT",
                "Arbitrage",
            ]
        ],
        use_container_width=True
    )

    st.download_button(
        "Download Analyzed Trades (CSV)",
        df.to_csv(index=False),
        "mt5_analyzed_trades.csv",
        mime="text/csv"
    )
