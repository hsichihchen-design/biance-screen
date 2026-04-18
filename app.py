import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 頁面配置與樣式優化
# ==========================================
st.set_page_config(page_title="Binance 1H 型態瀏覽器", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #ffffff; }
    [data-testid="stSidebar"] { display: none; }
    .stPlotlyChart { margin-bottom: 2rem; }
    .block-container { padding-top: 2rem; }
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 數據獲取模組 (Binance API)
# ==========================================
def fetch_binance_1h_data(symbol, limit=150):
    """從幣安 API 獲取 1H K線"""
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit={limit}"
    try:
        res = requests.get(url, timeout=5).json()
        df = pd.DataFrame(res, columns=[
            'Open_time', 'Open', 'High', 'Low', 'Close', 'Volume', 
            'Close_time', 'Quote_volume', 'Trades', 'Taker_buy_base', 'Taker_buy_quote', 'Ignore'
        ])
        df['Open_time'] = pd.to_datetime(df['Open_time'], unit='ms') + timedelta(hours=8)
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = df[col].astype(float)
        
        # 計算均線 (與 update_data.py 對齊)
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        return symbol, df
    except Exception:
        return symbol, pd.DataFrame()

@st.cache_data(ttl=300) # 幣圈變化快，緩存設為 5 分鐘
def load_all_charts_data(symbols):
    """並行下載所有幣種數據"""
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_symbol = {executor.submit(fetch_binance_1h_data, s): s for s in symbols}
        for future in future_to_symbol:
            sym, df = future.result()
            if not df.empty:
                results[sym] = df
    return results

# ==========================================
# 程式主邏輯
# ==========================================
def main():
    # 1. 讀取分析結果
    try:
        with open('uptrend_results.json', 'r', encoding='utf-8') as f:
            data_store = json.load(f)
    except FileNotFoundError:
        st.error("⚠️ 找不到 uptrend_results.json，請先執行掃描腳本。")
        return

    # 2. 標題與更新時間
    last_updated = data_store.get('last_updated', '未知')
    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        st.title("₿ Binance Futures 1H 強勢股")
    with col_t2:
        st.markdown(f"<div style='text-align:right; color:#666;'>最後更新: {last_updated}</div>", unsafe_allow_html=True)

    # 3. 準備清單
    all_results = data_store.get('results', [])
    symbol_list = sorted(list(set([r['symbol'] for r in all_results])))

    if not symbol_list:
        st.info("目前沒有符合篩選條件的幣種。")
        return

    # 4. 下載數據
    with st.spinner(f"正在同步 {len(symbol_list)} 檔合約即時 K 線..."):
        all_data = load_all_charts_data(symbol_list)

    # 5. 繪圖渲染
    cols = st.columns(2)
    for i, symbol in enumerate(symbol_list):
        if symbol not in all_data: continue
        
        df = all_data[symbol].tail(100) # 顯示最近 100 根 K 棒
        df['TimeStr'] = df['Open_time'].dt.strftime('%m-%d %H:00')

        # 建立圖表
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            row_heights=[0.75, 0.25], vertical_spacing=0.05)

        # K線圖
        fig.add_trace(go.Candlestick(
            x=df['TimeStr'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            increasing_line_color='#00c087', decreasing_line_color='#ff3b57',
            increasing_fillcolor='#00c087', decreasing_fillcolor='#ff3b57',
            name="K線"
        ), row=1, col=1)

        # 均線
        fig.add_trace(go.Scatter(x=df['TimeStr'], y=df['MA10'], line=dict(color='#FFD700', width=1.5), name='10MA'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['TimeStr'], y=df['MA20'], line=dict(color='#FF00FF', width=1.5), name='20MA'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['TimeStr'], y=df['MA60'], line=dict(color='#00BFFF', width=1.5), name='60MA'), row=1, col=1)

        # 成交量
        colors = ['#00c087' if c >= o else '#ff3b57' for c, o in zip(df['Close'], df['Open'])]
        fig.add_trace(go.Bar(x=df['TimeStr'], y=df['Volume'], marker_color=colors, name="成交量"), row=2, col=1)

        # 版面設定
        fig.update_layout(
            height=450,
            margin=dict(l=10, r=40, t=40, b=10),
            xaxis_rangeslider_visible=False,
            template="plotly_white",
            showlegend=False,
            title=dict(text=f"<b>{symbol} (1H)</b>", font=dict(size=20, color='#1e1e1e')),
            hovermode='x unified'
        )

        fig.update_xaxes(type='category', nticks=10, showgrid=True, gridcolor='#f0f0f0', row=1, col=1)
        fig.update_yaxes(side='right', showgrid=True, gridcolor='#f0f0f0', row=1, col=1)
        fig.update_yaxes(showticklabels=False, row=2, col=1)

        # 填入欄位
        with cols[i % 2]:
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            st.markdown("---")

if __name__ == "__main__":
    main()