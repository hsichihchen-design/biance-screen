import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "uptrend_results.json"
DEFAULT_ANALYSIS_BARS = 60

st.set_page_config(page_title="幣安掃圖｜MA30/45/60", layout="wide")

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
        font-size: 1.05rem !important;
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
    order = {"5m": 1, "15m": 2, "1h": 3, "4h": 4, "1d": 5}
    return order.get(timeframe, 999)


def choose_one_signal_per_symbol(results: list[dict]) -> list[dict]:
    """同幣種保留最近完成的波段；若同時完成則保留漲幅較大者。"""
    selected: dict[str, dict] = {}
    for result in results:
        symbol = result["symbol"]
        current_key = (result.get("end_date", ""), result.get("rise_pct", 0))
        previous = selected.get(symbol)
        previous_key = (
            (previous.get("end_date", ""), previous.get("rise_pct", 0))
            if previous
            else ("", -1)
        )
        if previous is None or current_key > previous_key:
            selected[symbol] = result
    return sorted(selected.values(), key=lambda item: item["symbol"])


def build_chart(result: dict, analysis_bars: int) -> go.Figure:
    symbol = result["symbol"]
    timeframe = result["timeframe"]
    frame = pd.DataFrame(result["kline_data"])

    if frame.empty:
        return go.Figure()

    frame["MA30"] = frame["c"].rolling(30).mean()
    frame["MA45"] = frame["c"].rolling(45).mean()
    frame["MA60"] = frame["c"].rolling(60).mean()
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
            y=plot_df["MA30"],
            line={"color": "#F28E2B", "width": 1.4},
            name="MA30",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=plot_df["t"],
            y=plot_df["MA45"],
            line={"color": "#4E79A7", "width": 1.4},
            name="MA45",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=plot_df["t"],
            y=plot_df["MA60"],
            line={"color": "#9C6ADE", "width": 1.6},
            name="MA60",
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

    rise_percent = result.get("rise_pct", 0) * 100
    pullback_percent = result.get("structure", {}).get("pullback_pct", 0) * 100
    tolerance_percent = (
        result.get("structure", {}).get("line_tolerance_pct", 0) * 100
    )
    duration = result.get("duration_bars", "-")
    signal_type = result.get("signal_type", "?")
    signal_name = result.get("signal_name", "未分類")
    type_color = "#0057B8" if signal_type == "A" else "#B35C00"

    figure.update_layout(
        height=460,
        margin={"l": 5, "r": 55, "t": 72, "b": 20},
        xaxis_rangeslider_visible=False,
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        title={
            "text": (
                f"<b>{symbol} ({timeframe})</b> "
                f"<span style='color:{type_color};font-size:14px'>"
                f"{signal_type}｜{signal_name}</span><br>"
                f"<span style='font-size:13px'>"
                f"主升 +{rise_percent:.1f}%｜回檔 {pullback_percent:.1f}%｜"
                f"容許帶 ±{tolerance_percent:.1f}%｜{duration} 根"
                f"</span>"
            ),
            "font": {"size": 20, "color": "#000000"},
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


def structure_caption(result: dict) -> str:
    structure = result.get("structure", {})
    ma30 = structure.get("ma30")
    ma45 = structure.get("ma45")
    ma60 = structure.get("ma60")
    ma60_slope = structure.get("ma60_slope_pct")
    tolerance = structure.get("line_tolerance_pct")
    near_ratio = structure.get("close_near_ma60_ratio")
    below_count = structure.get("max_consecutive_below_ma60")

    def fmt_price(value):
        if value is None:
            return "-"
        return f"{value:,.6g}"

    return (
        f"MA30 {fmt_price(ma30)}｜MA45 {fmt_price(ma45)}｜MA60 {fmt_price(ma60)}｜"
        f"MA60斜率 {(ma60_slope or 0) * 100:.2f}%｜"
        f"壓線容許 {(tolerance or 0) * 100:.1f}%｜"
        f"近10根守住MA60帶 {(near_ratio or 0) * 100:.0f}%｜"
        f"最長失守 {below_count or 0} 根"
    )


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
            <div style='font-size:2.1rem; font-weight:900; line-height:1.2;'>
                ₿ 幣安掃圖｜MA30 / MA45 / MA60
            </div>
            <div style='font-size:0.9rem; font-weight:800;'>更新：{last_updated}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        f"掃描 {summary.get('symbols_scanned', '-')} 個標的｜"
        f"A 順勢延續 {summary.get('type_a_signals', '-')} 組｜"
        f"B 均線壓回 {summary.get('type_b_signals', '-')} 組｜"
        f"失敗請求 {summary.get('failed_requests', '-')} 次"
    )

    available_timeframes = sorted(
        {result["timeframe"] for result in all_results},
        key=timeframe_sort_key,
    )
    if not available_timeframes:
        st.info("目前沒有符合 MA30/45/60 柔性趨勢結構的標的。")
        return

    selected_timeframe = st.radio(
        "觀測週期",
        available_timeframes,
        horizontal=True,
    )

    type_options = {
        "全部": None,
        "A｜順勢延續": "A",
        "B｜均線壓回": "B",
    }
    selected_type_label = st.radio(
        "型態",
        list(type_options.keys()),
        horizontal=True,
    )
    selected_type = type_options[selected_type_label]

    st.markdown("<hr style='border:1px solid #cccccc;'>", unsafe_allow_html=True)

    timeframe_results = [
        result
        for result in all_results
        if result["timeframe"] == selected_timeframe
        and (selected_type is None or result.get("signal_type") == selected_type)
    ]
    display_results = choose_one_signal_per_symbol(timeframe_results)
    st.caption(f"目前顯示 {len(display_results)} 個幣種；同幣種保留最近完成的波段。")

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
            st.caption(structure_caption(result))
            st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
