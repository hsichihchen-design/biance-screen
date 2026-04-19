import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json

st.set_page_config(page_title="Binance 多週期靜態看板", layout="wide")

# 極致白底與隱藏不必要的元素 (比照台股版本)
st.markdown("""
    <style>
    .main { background-color: #ffffff; }
    [data-testid="stSidebar"] { display: none; }
    .block-container { padding-top: 2rem; padding-bottom: 0rem; }
    </style>
    """, unsafe_allow_html=True)

def main():
    try:
        with open('uptrend_results.json', 'r', encoding='utf-8') as f:
            data_store = json.load(f)
    except FileNotFoundError:
        st.error("⚠️ 找不到預裝資料。")
        return

    last_updated = data_store.get('last_updated', '未知')
    all_results = data_store.get('results', [])
    
    col_t1, col_t2 = st.columns([3, 1])
    with col_t1:
        st.title("₿ Binance 多週期靜態看板")
    with col_t2:
        st.markdown(f"<div style='text-align:right; color:#555; padding-top: 25px;'><b>最後掃描時間</b><br>{last_updated}</div>", unsafe_allow_html=True)

    available_tfs = sorted(list(set([r['timeframe'] for r in all_results])))
    if not available_tfs:
        st.info("目前沒有符合標的。")
        return
        
    selected_tf = st.radio("選擇週期", available_tfs, horizontal=True)
    st.markdown("---")
    
    filtered_results = [r for r in all_results if r['timeframe'] == selected_tf]
    if not filtered_results:
        return

    # 幣圈標準配色 (與台股相反，綠漲紅跌)
    inc_color = '#00c087' 
    dec_color = '#ff3b57'

    for i, res in enumerate(filtered_results):
        symbol = res['symbol']
        df = pd.DataFrame(res['kline_data'])
        
        # 1. 在 180 根的基礎上計算均線 (這樣前 60 根也有數值了)
        df['MA10'] = df['c'].rolling(window=10).mean()
        df['MA20'] = df['c'].rolling(window=20).mean()
        df['MA60'] = df['c'].rolling(window=60).mean()
        
        # 2. 裁切最後 120 根出來畫圖 (MA60 會無縫接軌)
        plot_df = df.tail(120).copy()

        # 建立雙層圖表
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.03)
        
        # K線 (調整 width 讓 K 棒變得俐落不肥胖)
        fig.add_trace(go.Candlestick(
            x=plot_df['t'], open=plot_df['o'], high=plot_df['h'], low=plot_df['l'], close=plot_df['c'],
            increasing_line_color=inc_color, decreasing_line_color=dec_color,
            increasing_fillcolor=inc_color, decreasing_fillcolor=dec_color,
            increasing_line_width=0.8, decreasing_line_width=0.8,
            name="K線"
        ), row=1, col=1)

        # 均線配置
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA10'], line=dict(color='#f6c23e', width=1.2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA20'], line=dict(color='#8e44ad', width=1.2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA60'], line=dict(color='#36b9cc', width=1.2)), row=1, col=1)

        # 成交量
        v_colors = [inc_color if c >= o else dec_color for c, o in zip(plot_df['c'], plot_df['o'])]
        fig.add_trace(go.Bar(x=plot_df['t'], y=plot_df['v'], marker_color=v_colors), row=2, col=1)

        # 套用台股無留白、純靜態排版
        fig.update_layout(
            height=350,
            margin=dict(l=5, r=40, t=40, b=20),
            xaxis_rangeslider_visible=False,
            template="plotly_white",
            paper_bgcolor='white',
            plot_bgcolor='white',
            title=dict(text=f"<b>{symbol} ({selected_tf}) | 漲幅: {res['rise_pct']:.1%}</b>", font=dict(color='black', size=18)),
            showlegend=False,
            dragmode=False,   # 禁用拖曳
            hovermode=False   # 禁用懸停
        )
        
        # X / Y 軸隱藏網格線與關閉互動
        fig.update_xaxes(type='category', nticks=10, showgrid=False, zeroline=False, fixedrange=True, tickfont=dict(color='black', size=11), row=1, col=1)
        fig.update_xaxes(type='category', nticks=10, showgrid=False, zeroline=False, fixedrange=True, tickfont=dict(color='black', size=11), row=2, col=1)
        fig.update_yaxes(showgrid=False, zeroline=False, fixedrange=True, tickfont=dict(color='black', size=12), side='right', row=1, col=1)
        fig.update_yaxes(showgrid=False, zeroline=False, fixedrange=True, showticklabels=False, row=2, col=1)

        # 雙欄式排列邏輯
        if i % 2 == 0:
            cols = st.columns(2)
        
        with cols[i % 2]:
            st.plotly_chart(
                fig, 
                use_container_width=True, 
                config={'staticPlot': True, 'displayModeBar': False} # 完全轉換為靜態無互動圖片
            )
            st.markdown("<br>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
