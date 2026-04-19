import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json

# ==========================================
# 頁面配置與極致辨識度樣式
# ==========================================
st.set_page_config(page_title="Binance 結構看板", layout="wide")

# 強制所有文字為純黑，並優化手機端顯示
st.markdown("""
    <style>
    .main { background-color: #ffffff !important; }
    [data-testid="stSidebar"] { display: none; }
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
    /* 強制網頁所有文字顏色 */
    h1, h2, h3, p, span, div, label { color: #000000 !important; font-weight: 600 !important; }
    /* 修正 Radio Button 文字顏色 */
    .stRadio label { color: #000000 !important; font-size: 1.1rem !important; }
    </style>
    """, unsafe_allow_html=True)

def main():
    try:
        with open('uptrend_results.json', 'r', encoding='utf-8') as f:
            data_store = json.load(f)
    except FileNotFoundError:
        st.error("⚠️ 找不到數據，請執行 update_data.py。")
        return

    last_updated = data_store.get('last_updated', '未知')
    all_results = data_store.get('results', [])
    
    # 標題欄位
    col_t1, col_t2 = st.columns([3, 1])
    with col_t1: 
        st.markdown(f"<h1 style='color: #000000; font-size: 2.2rem;'>₿ Binance 180K 階梯式結構</h1>", unsafe_allow_html=True)
    with col_t2: 
        st.markdown(f"<div style='text-align:right; color:#000000; padding-top:20px; font-weight:bold;'>最後掃描<br>{last_updated}</div>", unsafe_allow_html=True)

    # 取得可用週期
    available_tfs = sorted(list(set([r['timeframe'] for r in all_results])))
    if not available_tfs:
        st.info("目前無符合結構之標的。")
        return
        
    selected_tf = st.radio("觀測週期", available_tfs, horizontal=True)
    st.markdown("<hr style='border: 1px solid #000000;'>", unsafe_allow_html=True)
    
    # ==========================================
    # 核心邏輯：過濾重複標的，每個幣種僅保留漲幅最大的一張圖
    # ==========================================
    tf_results = [r for r in all_results if r['timeframe'] == selected_tf]
    unique_dict = {}
    for r in tf_results:
        sym = r['symbol']
        # 如果同一個幣有多次上漲，保留漲幅最高的
        if sym not in unique_dict or r['rise_pct'] > unique_dict[sym]['rise_pct']:
            unique_dict[sym] = r
    
    display_results = list(unique_dict.values())
    
    inc_color, dec_color = '#00c087', '#ff3b57'

    for i, res in enumerate(display_results):
        symbol = res['symbol']
        df = pd.DataFrame(res['kline_data'])
        df['MA10'] = df['c'].rolling(10).mean()
        df['MA20'] = df['c'].rolling(20).mean()
        df['MA60'] = df['c'].rolling(60).mean()
        
        plot_df = df.tail(180).copy()

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.03)
        
        # K線
        fig.add_trace(go.Candlestick(
            x=plot_df['t'], open=plot_df['o'], high=plot_df['h'], low=plot_df['l'], close=plot_df['c'],
            increasing_line_color=inc_color, decreasing_line_color=dec_color,
            increasing_fillcolor=inc_color, decreasing_fillcolor=dec_color,
            increasing_line_width=0.9, decreasing_line_width=0.9
        ), row=1, col=1)

        # 均線 (加深顏色與粗度)
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA10'], line=dict(color='#d4af37', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA20'], line=dict(color='#8e44ad', width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA60'], line=dict(color='#1f77b4', width=2.0)), row=1, col=1)

        # 成交量
        v_colors = [inc_color if c >= o else dec_color for c, o in zip(plot_df['c'], plot_df['o'])]
        fig.add_trace(go.Bar(x=plot_df['t'], y=plot_df['v'], marker_color=v_colors), row=2, col=1)

        # 套用純黑高辨識度排版
        fig.update_layout(
            height=420, margin=dict(l=5, r=50, t=50, b=20), xaxis_rangeslider_visible=False,
            template="plotly_white", paper_bgcolor='white', plot_bgcolor='white',
            title=dict(
                text=f"<b>{symbol} ({selected_tf}) | 偵測漲幅: {res['rise_pct']:.1%}</b>", 
                font=dict(size=22, color='#000000'),
                x=0.01
            ),
            showlegend=False, dragmode=False, hovermode=False
        )
        
        # 坐標軸文字全部強制為純黑、加粗
        axis_style = dict(showgrid=False, fixedrange=True, tickfont=dict(color='#000000', size=13, family="Arial Black"))
        
        fig.update_xaxes(type='category', nticks=10, **axis_style, row=1, col=1)
        fig.update_xaxes(type='category', nticks=10, **axis_style, row=2, col=1)
        fig.update_yaxes(**axis_style, side='right', row=1, col=1)
        fig.update_yaxes(showgrid=False, fixedrange=True, showticklabels=False, row=2, col=1)

        # 雙欄排列
        if i % 2 == 0:
            layout_cols = st.columns(2)
        
        with layout_cols[i % 2]:
            st.plotly_chart(
                fig, 
                use_container_width=True, 
                theme=None, # 禁用 Streamlit 主題，強制使用 Plotly 自定義顏色
                config={'staticPlot': True, 'displayModeBar': False}
            )
            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
