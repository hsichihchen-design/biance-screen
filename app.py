import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json

st.set_page_config(page_title="Binance 180K 結構看板", layout="wide")

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
        st.error("⚠️ 找不到數據，請執行 update_data.py。")
        return

    last_updated = data_store.get('last_updated', '未知')
    all_results = data_store.get('results', [])
    
    col_t1, col_t2 = st.columns([3, 1])
    
    with col_t1: 
        st.title("₿ Binance 180K 階梯式結構看板")
        
    with col_t2: 
        st.markdown(f"<div style='text-align:right; color:#555; padding-top:25px;'><b>最後掃描</b><br>{last_updated}</div>", unsafe_allow_html=True)

    available_tfs = sorted(list(set([r['timeframe'] for r in all_results])))
    if not available_tfs:
        st.info("全市場無符合 180 根階梯墊高結構之標的。")
        return
        
    selected_tf = st.radio("觀測週期", available_tfs, horizontal=True)
    st.markdown("---")
    
    filtered_results = [r for r in all_results if r['timeframe'] == selected_tf]
    inc_color, dec_color = '#00c087', '#ff3b57'

    for i, res in enumerate(filtered_results):
        df = pd.DataFrame(res['kline_data'])
        df['MA10'] = df['c'].rolling(10).mean()
        df['MA20'] = df['c'].rolling(20).mean()
        df['MA60'] = df['c'].rolling(60).mean()
        
        # 核心修改：裁切最後 180 根，此時 MA60 因有前 60 根緩衝，會是飽滿的
        plot_df = df.tail(180).copy()

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.03)
        
        # K線 (寬度 0.8 保持俐落)
        fig.add_trace(go.Candlestick(
            x=plot_df['t'], open=plot_df['o'], high=plot_df['h'], low=plot_df['l'], close=plot_df['c'],
            increasing_line_color=inc_color, decreasing_line_color=dec_color,
            increasing_fillcolor=inc_color, decreasing_fillcolor=dec_color,
            increasing_line_width=0.8, decreasing_line_width=0.8
        ), row=1, col=1)

        # 均線
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA10'], line=dict(color='#f6c23e', width=1.1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA20'], line=dict(color='#8e44ad', width=1.1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA60'], line=dict(color='#36b9cc', width=1.3)), row=1, col=1)

        # 成交量
        v_colors = [inc_color if c >= o else dec_color for c, o in zip(plot_df['c'], plot_df['o'])]
        fig.add_trace(go.Bar(x=plot_df['t'], y=plot_df['v'], marker_color=v_colors), row=2, col=1)

        fig.update_layout(
            height=380, margin=dict(l=5, r=45, t=40, b=20), xaxis_rangeslider_visible=False,
            template="plotly_white", paper_bgcolor='white', plot_bgcolor='white',
            title=dict(text=f"<b>{res['symbol']} ({selected_tf}) | 波段漲幅: {res['rise_pct']:.1%}</b>", font=dict(size=18)),
            showlegend=False, dragmode=False, hovermode=False
        )
        
        fig.update_xaxes(type='category', nticks=12, showgrid=False, fixedrange=True, tickfont=dict(size=10), row=1, col=1)
        fig.update_xaxes(type='category', nticks=12, showgrid=False, fixedrange=True, tickfont=dict(size=10), row=2, col=1)
        fig.update_yaxes(showgrid=False, fixedrange=True, side='right', row=1, col=1)
        fig.update_yaxes(showgrid=False, fixedrange=True, showticklabels=False, row=2, col=1)

        if i % 2 == 0: cols = st.columns(2)
        with cols[i % 2]:
            st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False})
            st.markdown("<br>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
