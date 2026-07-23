import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "uptrend_results.json"
DEFAULT_ANALYSIS_BARS = 60

st.set_page_config(page_title="幣安掃圖｜60 根", layout="wide")

st.markdown(
    """
    <style>
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background-color: #ffffff !important;
    }
    .stApp * {
        color: #000000 !important;
        font-family: "Arial", sans-serif !important;
    }
    .stRadio p {
        font-size: 1.1rem !important;
        font-weight: 700 !important;
    }
    [data-testid="stSidebar"] { display: none; }
    .block-container { padding-top: 1rem; padding-bottom: 0rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_data() -> dict:
    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        st.error("⚠️ 找不到 uptrend_results.json，請先執行 update_data.py。")
    except json.JSONDecodeError as exc:
        st.error(f"⚠️ JSON 格式錯誤：{exc}")
    return {}


def timeframe_sort_key(timeframe: str) -> int:
    order = {"5m": 1, "15m": 2, "1h": 3, "4h": 4}
    return order.get(timeframe, 999)


def choose_one_signal_per_symbol(results: list[dict]) -> list[dict]:
    """同週期、同幣種若有多段訊號，只保留漲幅最大的那一段。"""
    selected: dict[str, dict] = {}
    for result in results:
        symbol = result["symbol"]
        if symbol not in selected or result["rise_pct"] > selected[symbol]["rise_pct"]:
            selected[symbol] = result
    return sorted(selected.values(), key=lambda item: item["symbol"])


def build_chart(result: dict, analysis_bars: int) -> go.Figure:
    symbol = result["symbol"]
    timeframe = result["timeframe"]
    frame = pd.DataFrame(result["kline_data"])

    if frame.empty:
        return go.Figure()

    # 60 根版本使用 MA10 / MA15 / MA20。
    frame["MA10"] = frame["c"].rolling(10).mean()
    frame["MA15"] = frame["c"].rolling(15).mean()
    frame["MA20"] = frame["c"].rolling(20).mean()
    plot_df = frame.tail(analysis_bars).copy()

    all_times = plot_df["t"].tolist()
    tick_step = max(1, len(all_times) // 6)
    tick_values = all_times[::tick_step]
    tick_text = [value.split(" ")[0] for value in tick_values]

    increasing_color = "#E32636"
    decreasing_color = "#008F39"

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.80, 0.20],
        vertical_spacing=0.03,
    )

    figure.add_trace(
        go.Candlestick(
            x=plot_df["t"],
            open=plot_df["o"],
            high=plot_df["h"],
            low=plot_df["l"],
            close=plot_df["c"],
            increasing_line_color=increasing_color,
            decreasing_line_color=decreasing_color,
            increasing_fillcolor=increasing_color,
            decreasing_fillcolor=decreasing_color,
            increasing_line_width=0.8,
            decreasing_line_width=0.8,
            name="K 線",
        ),
        row=1,
        col=1,
    )

    figure.add_trace(
        go.Scatter(
            x=plot_df["t"],
            y=plot_df["MA10"],
            line={"color": "#F75000", "width": 1.2},
            name="MA10",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=plot_df["t"],
            y=plot_df["MA15"],
            line={"color": "#9F0050", "width": 1.2},
            name="MA15",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=plot_df["t"],
            y=plot_df["MA20"],
            line={"color": "#6C3365", "width": 1.3},
            name="MA20",
        ),
        row=1,
        col=1,
    )

    volume_colors = [
        increasing_color if close >= open_ else decreasing_color
        for close, open_ in zip(plot_df["c"], plot_df["o"])
    ]
    figure.add_trace(
        go.Bar(
            x=plot_df["t"],
            y=plot_df["v"],
            marker_color=volume_colors,
            name="成交量",
        ),
        row=2,
        col=1,
    )

    # 把程式實際判斷的低點、高點畫出來，不再只顯示未標記的 K 線。
    start_label = result.get("start_label")
    end_label = result.get("end_label")
    if start_label in all_times:
        figure.add_trace(
            go.Scatter(
                x=[start_label],
                y=[result["start_price"]],
                mode="markers+text",
                marker={"size": 10, "symbol": "triangle-up", "color": "#0057B8"},
                text=["起點"],
                textposition="bottom center",
                name="波段低點",
            ),
            row=1,
            col=1,
        )
    if end_label in all_times:
        figure.add_trace(
            go.Scatter(
                x=[end_label],
                y=[result["end_price"]],
                mode="markers+text",
                marker={"size": 10, "symbol": "triangle-down", "color": "#111111"},
                text=["高點"],
                textposition="top center",
                name="波段高點",
            ),
            row=1,
            col=1,
        )

    rise_percent = result["rise_pct"] * 100
    duration = result.get("duration_bars", "-")
    figure.update_layout(
        height=430,
        margin={"l": 5, "r": 55, "t": 62, "b": 20},
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        title={
            "text": (
                f"<b>{symbol} ({timeframe})</b> "
                f"<span style='font-size:14px'>+{rise_percent:.1f}%｜{duration} 根</span>"
            ),
            "font": {"size": 21, "color": "#000000"},
            "x": 0.01,
        },
        showlegend=False,
        dragmode=False,
        hovermode=False,
    )

    axis_style = {
        "showgrid": False,
        "fixedrange": True,
        "tickfont": {"color": "#000000", "size": 11, "family": "Arial Black"},
    }
    figure.update_xaxes(
        type="category",
        tickmode="array",
        tickvals=tick_values,
        ticktext=tick_text,
        **axis_style,
        row=1,
        col=1,
    )
    figure.update_xaxes(
        type="category",
        tickmode="array",
        tickvals=tick_values,
        ticktext=tick_text,
        **axis_style,
        row=2,
        col=1,
    )
    figure.update_yaxes(**axis_style, side="right", row=1, col=1)
    figure.update_yaxes(
        showgrid=False,
        fixedrange=True,
        showticklabels=False,
        row=2,
        col=1,
    )
    return figure


def main() -> None:
    data_store = load_data()
    if not data_store:
        return

    last_updated = data_store.get("last_updated", "未知")
    settings = data_store.get("settings", {})
    summary = data_store.get("summary", {})
    all_results = data_store.get("results", [])
    analysis_bars = int(settings.get("analysis_bars", DEFAULT_ANALYSIS_BARS))

    st.markdown(
        f"""
        <div style='display:flex; justify-content:space-between; align-items:baseline;
                    border-bottom:2px solid #000000; padding-top:25px;
                    padding-bottom:5px; margin-bottom:10px;'>
            <div style='font-size:2.2rem; font-weight:900; line-height:1.2;'>
                ₿ 幣安掃圖｜{analysis_bars} 根
            </div>
            <div style='font-size:0.9rem; font-weight:800;'>更新：{last_updated}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        f"掃描 {summary.get('symbols_scanned', '-')} 個標的｜"
        f"訊號 {summary.get('signals_found', len(all_results))} 組｜"
        f"失敗請求 {summary.get('failed_requests', '-')} 次"
    )

    available_timeframes = sorted(
        {result["timeframe"] for result in all_results},
        key=timeframe_sort_key,
    )
    if not available_timeframes:
        st.info("目前沒有符合 60 根上漲結構的標的。")
        return

    selected_timeframe = st.radio(
        "觀測週期",
        available_timeframes,
        horizontal=True,
    )
    st.markdown("<hr style='border:1px solid #cccccc;'>", unsafe_allow_html=True)

    timeframe_results = [
        result
        for result in all_results
        if result["timeframe"] == selected_timeframe
    ]
    display_results = choose_one_signal_per_symbol(timeframe_results)
    st.caption(f"目前顯示 {len(display_results)} 個幣種；同幣種只保留漲幅最大波段。")

    layout_columns = None
    for index, result in enumerate(display_results):
        if index % 2 == 0:
            layout_columns = st.columns(2)

        with layout_columns[index % 2]:
            figure = build_chart(result, analysis_bars)
            st.plotly_chart(
                figure,
                use_container_width=True,
                theme=None,
                config={"staticPlot": True, "displayModeBar": False},
            )
            st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
