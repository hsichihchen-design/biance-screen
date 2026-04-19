import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json

st.set_page_config(page_title="Binance 離線型態瀏覽器", layout="wide")

def main():
    try:
        with open('uptrend_results.json', 'r', encoding='utf-8') as f:
            data_store = json.load(f)
    except FileNotFoundError:
        st.error("⚠️ 找不到預裝資料。")
        return

    last_updated = data_store.get('last_updated', '未知')
    all_results = data_store.get('results', [])
    
    # 側邊欄標題
    st.title("₿ Binance 多週期預渲染看板")
    st.caption(f"資料最後更新時間: {last_updated}")

    # 1. 週期過濾
    available_tfs = sorted(list(set([r['timeframe'] for r in all_results])))
    selected_tf = st.radio("選擇週期", available_tfs, horizontal=True)
    
    filtered_results = [r for r in all_results if r['timeframe'] == selected_tf]
    
    if not filtered_results:
        st.info("該週期目前沒有符合條件的標的。")
        return

    # 2. 顯示圖表
    cols = st.columns(2)
    for i, res in enumerate(filtered_results):
        symbol = res['symbol']
        k_data = res['kline_data']
        df = pd.DataFrame(k_data) # 直接從 JSON 轉成 DataFrame
        
        # 繪圖邏輯 (直接使用 df['t'], df['o']...)
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
        
        fig.add_trace(go.Candlestick(
            x=df['t'], open=df['o'], high=df['h'], low=df['l'], close=df['c'],
            increasing_line_color='#00c087', decreasing_line_color='#ff3b57'
        ), row=1, col=1)

        # 計算前端均線 (因為是離線資料，我們在前端算這 120 根的均線)
        df['ma10'] = df['c'].rolling(window=10).mean()
        df['ma20'] = df['c'].rolling(window=20).mean()
        df['ma60'] = df['c'].rolling(window=60).mean()

        fig.add_trace(go.Scatter(x=df['t'], y=df['ma10'], line=dict(color='#FFD700', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['t'], y=df['ma20'], line=dict(color='#FF00FF', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['t'], y=df['ma60'], line=dict(color='#00BFFF', width=1)), row=1, col=1)

        colors = ['#00c087' if c >= o else '#ff3b57' for c, o in zip(df['c'], df['o'])]
        fig.add_trace(go.Bar(x=df['t'], y=df['v'], marker_color=colors), row=2, col=1)

        fig.update_layout(
            height=400, margin=dict(l=10, r=40, t=40, b=10), xaxis_rangeslider_visible=False,
            template="plotly_white", showlegend=False,
            title=dict(text=f"<b>{symbol} ({selected_tf}) | 漲幅: {res['rise_pct']:.1%}</b>")
        )
        fig.update_xaxes(type='category', nticks=8)
        fig.update_yaxes(side='right')

        with cols[i % 2]:
            st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
