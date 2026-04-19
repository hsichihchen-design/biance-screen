import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json

# ==========================================
# 頁面配置與極致辨識度樣式 (強制抵抗手機深色模式)
# ==========================================
st.set_page_config(page_title="幣安掃圖", layout="wide")

st.markdown("""
    <style>
    /* 1. 強制整個網頁的底層背景為純白 */
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background-color: #ffffff !important;
    }
    
    /* 2. 強制網頁內所有的文字為純黑、加粗 */
    .stApp * {
        color: #000000 !important;
        font-family: "Arial", sans-serif !important;
    }
    
    /* 3. 特別放大上方 Radio 按鈕的文字與排版 */
    .stRadio p {
        font-size: 1.1rem !important;
        font-weight: 700 !important;
    }
    
    /* 4. 隱藏側邊欄與縮減頂部邊距 */
    [data-testid="stSidebar"] { display: none; }
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
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
    # 標題與更新時間合併為單一欄位
    st.markdown(f"""
        <div style='display: flex; justify-content: space-between; align-items: baseline; border-bottom: 2px solid #000000; padding-top: 25px; padding-bottom: 5px; margin-bottom: 10px;'>
            <div style='font-size: 2.2rem; font-weight: 900; color: #000000; line-height: 1.2;'>₿ 幣安掃圖</div>
            <div style='font-size: 0.9rem; font-weight: 800; color: #000000;'>更新：{last_updated}</div>
        </div>
        """, unsafe_allow_html=True)

    # 取得可用週期
    available_tfs = sorted(list(set([r['timeframe'] for r in all_results])))
    if not available_tfs:
        st.info("目前無符合結構之標的。")
        return
        
    selected_tf = st.radio("觀測週期", available_tfs, horizontal=True)
    st.markdown("<hr style='border: 1px solid #cccccc;'>", unsafe_allow_html=True)
    
    # ==========================================
    # 核心邏輯：過濾重複標的，每個幣種僅保留漲幅最大的一張圖
    # ==========================================
    tf_results = [r for r in all_results if r['timeframe'] == selected_tf]
    unique_dict = {}
    for r in tf_results:
        sym = r['symbol']
        # 如果同一個幣有多次上漲信號，只保留漲幅最高的那一個
        if sym not in unique_dict or r['rise_pct'] > unique_dict[sym]['rise_pct']:
            unique_dict[sym] = r
    
    display_results = sorted(list(unique_dict.values()), key=lambda x: x['symbol'])
    
    inc_color, dec_color = '#E32636', '#008F39'

    for i, res in enumerate(display_results):
        symbol = res['symbol']
        df = pd.DataFrame(res['kline_data'])
        df['MA30'] = df['c'].rolling(30).mean()
        df['MA45'] = df['c'].rolling(45).mean()
        df['MA60'] = df['c'].rolling(60).mean()
        
        plot_df = df.tail(180).copy()

        # ==========================================
        # 核心修改：X 軸文字裁切，只顯示日期 (MM-DD)
        # ==========================================
        all_times = plot_df['t'].tolist()
        step = max(1, len(all_times) // 6)  # 自動均分 6 個刻度，避免擁擠
        tick_vals = all_times[::step]
        # split(' ')[0] 會把 "04-19 13:00" 切割，只留下前面的 "04-19"
        tick_text = [val.split(' ')[0] for val in tick_vals] 

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.8, 0.2], vertical_spacing=0.03)
        
        # K線
        fig.add_trace(go.Candlestick(
            x=plot_df['t'], open=plot_df['o'], high=plot_df['h'], low=plot_df['l'], close=plot_df['c'],
            increasing_line_color=inc_color, decreasing_line_color=dec_color,
            increasing_fillcolor=inc_color, decreasing_fillcolor=dec_color,
            increasing_line_width=0.7, decreasing_line_width=0.7
        ), row=1, col=1)

        # 均線 (稍微加粗以提升辨識度)
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA30'], line=dict(color='#F75000', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA45'], line=dict(color='#9F0050', width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=plot_df['t'], y=plot_df['MA60'], line=dict(color='#6C3365', width=1)), row=1, col=1)

        # 成交量
        v_colors = [inc_color if c >= o else dec_color for c, o in zip(plot_df['c'], plot_df['o'])]
        fig.add_trace(go.Bar(x=plot_df['t'], y=plot_df['v'], marker_color=v_colors), row=2, col=1)

        # 套用純黑高辨識度排版
        fig.update_layout(
            height=420, margin=dict(l=5, r=50, t=50, b=20), xaxis_rangeslider_visible=False,
            template="plotly_white", paper_bgcolor='white', plot_bgcolor='white',
            title=dict(
                text=f"<b>{symbol} ({selected_tf})</b>", 
                font=dict(size=22, color='#000000'), # 強制圖表標題為純黑
                x=0.01
            ),
            showlegend=False, dragmode=False, hovermode=False
        )
        
        # 坐標軸文字全部強制為純黑、加粗
        axis_style = dict(showgrid=False, fixedrange=True, tickfont=dict(color='#000000', size=12, family="Arial Black"))
        
        # 套用自訂的 X 軸刻度 (只有日期)
        fig.update_xaxes(type='category', tickmode='array', tickvals=tick_vals, ticktext=tick_text, **axis_style, row=1, col=1)
        fig.update_xaxes(type='category', tickmode='array', tickvals=tick_vals, ticktext=tick_text, **axis_style, row=2, col=1)
        
        fig.update_yaxes(**axis_style, side='right', row=1, col=1)
        fig.update_yaxes(showgrid=False, fixedrange=True, showticklabels=False, row=2, col=1)

        # 雙欄排列
        if i % 2 == 0:
            layout_cols = st.columns(2)
        
        with layout_cols[i % 2]:
            st.plotly_chart(
                fig, 
                use_container_width=True, 
                theme=None, # 【關鍵設定】：禁用 Streamlit 自動主題，防止它把文字刷白
                config={'staticPlot': True, 'displayModeBar': False}
            )
            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)

if __name__ == "__main__":
    main()
