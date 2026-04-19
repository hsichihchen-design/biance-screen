import streamlit as st
import pandas as pd
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="Binance 多週期型態瀏覽器", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #ffffff; }
    [data-testid="stSidebar"] { display: none; }
    .stPlotlyChart { margin-bottom: 2rem; }
    .block-container { padding-top: 2rem; }
    </style>
    """, unsafe_allow_html=True)

def fetch_binance_data(symbol, interval, limit=150):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=5).json()
        df = pd.DataFrame(res, columns=[
            'Open_time', 'Open', 'High', 'Low', 'Close', 'Volume', 
            'Close_time', 'Quote_volume', 'Trades', 'Taker_buy_base', 'Taker_buy_quote', 'Ignore'
        ])
        df['Open_time'] = pd.to_datetime(df['Open_time'], unit='ms') + timedelta(hours=8)
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = df[col].astype(float)
        
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        return symbol, df
    except Exception:
        return symbol, pd.DataFrame()

@st.cache_data(ttl=120) 
def load_all_charts_data(symbol_tf_pairs):
    results = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_pair = {executor.submit(fetch_binance_data, s, tf): (s, tf) for s, tf in symbol_tf_pairs}
        for future in future_to_pair:
            sym, df = future.result()
            tf = future_to_pair[future][1]
            if not df.empty:
                results[f"{sym}_{tf}"] = df
    return results

def main():
    try:
        with open('uptrend_results.json', 'r', encoding='utf-8') as f:
            data_store = json.load(f)
    except FileNotFoundError:
        st.error("⚠️ 找不到 uptrend_results.json，請先執行掃描腳本。")
        return

    last_updated = data_store.get('last_updated', '未知')
    all_results = data_store.get('results', [])
    
    # 提取 JSON 中有的時間週期並排序
    available_tfs = list(set([r.get('timeframe', '1h') for r in all_results]))
    tf_order = {'3m': 1, '15m': 2, '1h': 3, '8h': 4}
    available_tfs.sort(key=lambda x: tf_order.get(x, 99))

    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        st.title("₿ Binance 多週期合約強勢股")
    with col_t2:
        st.markdown(f"<div style='text-align:right; color:#666;'>最後掃描時間: {last_updated}</div>", unsafe_allow_html=True)

    if not available_tfs:
        st.info("目前全市場沒有符合您嚴格條件的幣種，請等待下一次排程掃描。")
        return

    # 建立多週期切換按鈕
    st.markdown("### 選擇觀測週期")
    selected_tf = st.radio("", available_tfs, horizontal=True, label_visibility="collapsed")
    st.markdown("---")

    filtered_results = [r for r in all_results if r.get('timeframe') == selected_tf]
    symbol_list = sorted(list(set([r['symbol'] for r in filtered_results])))
    
    if not symbol_list:
        st.warning(f"目前 {selected_tf} 週期沒有符合標的。")
        return

    pairs_to_fetch = [(s, selected_tf) for s in symbol_list]

    with st.spinner(f"正在同步 {selected_tf} 級別即時 K 線..."):
        all_data = load_all_charts_data(pairs_to_fetch)

    cols = st.columns(2)
    for i, symbol in enumerate(symbol_list):
        data_key = f"{symbol}_{selected_tf}"
        if data_key not in all_data: continue
        
        # 統一顯示最後 120 根，對齊您的分析基準
        df = all_data[data_key].tail(120) 
        
        if selected_tf in ['3m', '15m']:
            df['TimeStr'] = df['Open_time'].dt.strftime('%m-%d %H:%M')
        else:
            df['TimeStr'] = df['Open_time'].dt.strftime('%m-%d %H:00')

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.05)

        fig.add_trace(go.Candlestick(
            x=df['TimeStr'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            increasing_line_color='#00c087', decreasing_line_color='#ff3b57',
            increasing_fillcolor='#00c087', decreasing_fillcolor='#ff3b57'
        ), row=1, col=1)

        fig.add_trace(go.Scatter(x=df['TimeStr'], y=df['MA10'], line=dict(color='#FFD700', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['TimeStr'], y=df['MA20'], line=dict(color='#FF00FF', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['TimeStr'], y=df['MA60'], line=dict(color='#00BFFF', width=1.5)), row=1, col=1)

        colors = ['#00c087' if c >= o else '#ff3b57' for c, o in zip(df['Close'], df['Open'])]
        fig.add_trace(go.Bar(x=df['TimeStr'], y=df['Volume'], marker_color=colors), row=2, col=1)

        max_rise = max([r['rise_pct'] for r in filtered_results if r['symbol'] == symbol])
        
        fig.update_layout(
            height=450, margin=dict(l=10, r=40, t=40, b=10), xaxis_rangeslider_visible=False,
            template="plotly_white", showlegend=False,
            title=dict(text=f"<b>{symbol} ({selected_tf}) | 偵測漲幅: {max_rise:.1%}</b>", font=dict(size=18, color='#1e1e1e')),
            hovermode='x unified'
        )
        fig.update_xaxes(type='category', nticks=10, showgrid=True, gridcolor='#f0f0f0', row=1, col=1)
        fig.update_yaxes(side='right', showgrid=True, gridcolor='#f0f0f0', row=1, col=1)
        fig.update_yaxes(showticklabels=False, row=2, col=1)

        with cols[i % 2]:
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            st.markdown("---")

if __name__ == "__main__":
    main()
