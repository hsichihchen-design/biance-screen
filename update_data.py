import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import ccxt
import pandas as pd
import requests

# ==========================================
# 60 根 K 棒專用參數
# ==========================================
# rise：一段已確認的局部低點到局部高點，至少需要上漲多少
# gap：最近價格平台，相對於分析區前段平台至少抬高多少
# min_duration / max_duration：一段上漲至少／最多允許持續幾根 K 棒
TF_CONFIG = {
    "5m": {
        "interval": "5m",
        "rise": 0.025,
        "gap": 0.015,
        "min_duration": 3,
        "max_duration": 30,
    },
    "15m": {
        "interval": "15m",
        "rise": 0.045,
        "gap": 0.030,
        "min_duration": 3,
        "max_duration": 30,
    },
    "1h": {
        "interval": "1h",
        "rise": 0.070,
        "gap": 0.050,
        "min_duration": 3,
        "max_duration": 30,
    },
    "4h": {
        "interval": "4h",
        "rise": 0.100,
        "gap": 0.080,
        "min_duration": 3,
        "max_duration": 30,
    },
}

# ==========================================
# 60 根結構判斷參數
# ==========================================
ANALYSIS_BARS = 60
TREND_MA = 20
MA_SLOPE_BARS = 5

# 前 10 根代表舊平台；最後 5 根代表現在平台
BASE_ZONE_BARS = 10
RECENT_ZONE_BARS = 5

# 左右各 4 根，共 9 根 K 棒確認一個局部轉折
PIVOT_LOOKBACK = 4

# 高低點太靠近時視為同一個轉折區，只保留更極端者
PIVOT_MERGE_DISTANCE = 2

# 高點形成後至少再過 2 根 K 棒，才視為已確認
COOLING_BARS = 2

# 為 MA20 提供歷史緩衝，JSON 實際打包 80 根，畫面只顯示最後 60 根
PACK_BARS = ANALYSIS_BARS + TREND_MA
FETCH_LIMIT = 120

OUTPUT_FILE = Path(__file__).resolve().parent / "uptrend_results.json"

session = requests.Session()
session.headers.update({"User-Agent": "binance-screen/60-bars"})


def get_all_binance_futures() -> list[str]:
    """取得幣安所有有效的 USDT 本位永續合約代號。"""
    print("正在透過 CCXT 獲取全市場 U 本位永續合約清單...")
    try:
        exchange = ccxt.binance(
            {
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }
        )
        markets = exchange.load_markets()
        symbols = sorted(
            {
                market["id"]
                for market in markets.values()
                if market.get("type") == "swap"
                and market.get("quote") == "USDT"
                and market.get("active", True)
            }
        )
        print(f"✅ 成功獲取 {len(symbols)} 檔合約標的。")
        return symbols
    except Exception as exc:
        print(f"⚠️ 獲取完整市場清單失敗：{exc}")
        print("改用 BTC、ETH、SOL、BNB 作為備援清單。")
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]


def fetch_klines(
    symbol: str,
    interval: str,
    limit: int = FETCH_LIMIT,
    max_retries: int = 3,
) -> pd.DataFrame:
    """從幣安期貨 API 取得 K 線；遇到暫時性錯誤會重試。"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, params=params, timeout=10)
            response.raise_for_status()
            payload = response.json()

            if isinstance(payload, dict):
                raise RuntimeError(
                    f"Binance API error {payload.get('code')}: {payload.get('msg')}"
                )
            if not payload:
                return pd.DataFrame()

            columns = [
                "Open_time",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
                "Close_time",
                "Quote_volume",
                "Trades",
                "Taker_buy_base",
                "Taker_buy_quote",
                "Ignore",
            ]
            df = pd.DataFrame(payload, columns=columns)
            numeric_columns = ["Open", "High", "Low", "Close", "Volume"]
            df[numeric_columns] = df[numeric_columns].apply(
                pd.to_numeric, errors="coerce"
            )
            df.dropna(subset=numeric_columns, inplace=True)
            df["Open_time"] = pd.to_datetime(df["Open_time"], unit="ms", utc=True)
            df["Open_time"] = df["Open_time"].dt.tz_convert("Asia/Taipei")
            df.set_index("Open_time", inplace=True)
            return df

        except Exception as exc:
            if attempt == max_retries:
                print(f"\n⚠️ {symbol} {interval} 下載失敗：{exc}")
                return pd.DataFrame()
            time.sleep(0.8 * attempt)

    return pd.DataFrame()


def merge_nearby_pivots(
    pivots: list[tuple[int, float, pd.Timestamp]],
    kind: str,
) -> list[tuple[int, float, pd.Timestamp]]:
    """合併距離過近的同類轉折點，避免同一平台被重複計算。"""
    if not pivots:
        return []

    merged = [pivots[0]]
    for pivot in pivots[1:]:
        previous = merged[-1]
        if pivot[0] - previous[0] <= PIVOT_MERGE_DISTANCE:
            if kind == "high" and pivot[1] > previous[1]:
                merged[-1] = pivot
            elif kind == "low" and pivot[1] < previous[1]:
                merged[-1] = pivot
        else:
            merged.append(pivot)
    return merged


def find_pivots(
    recent_df: pd.DataFrame,
) -> tuple[
    list[tuple[int, float, pd.Timestamp]],
    list[tuple[int, float, pd.Timestamp]],
]:
    """
    使用左右各 4 根 K 棒確認局部高低點。

    為避免平頂／平底重複入選，中心點除了必須等於區間極值，
    還必須至少嚴格高於或低於窗口內其中一側的鄰近值。
    """
    highs: list[tuple[int, float, pd.Timestamp]] = []
    lows: list[tuple[int, float, pd.Timestamp]] = []

    for index in range(PIVOT_LOOKBACK, len(recent_df) - PIVOT_LOOKBACK):
        window = recent_df.iloc[
            index - PIVOT_LOOKBACK : index + PIVOT_LOOKBACK + 1
        ]
        center_high = float(recent_df["High"].iloc[index])
        center_low = float(recent_df["Low"].iloc[index])

        other_highs = window["High"].drop(window.index[PIVOT_LOOKBACK])
        other_lows = window["Low"].drop(window.index[PIVOT_LOOKBACK])

        is_high = (
            center_high == float(window["High"].max())
            and center_high > float(other_highs.min())
        )
        is_low = (
            center_low == float(window["Low"].min())
            and center_low < float(other_lows.max())
        )

        if is_high:
            highs.append((index, center_high, recent_df.index[index]))
        if is_low:
            lows.append((index, center_low, recent_df.index[index]))

    return (
        merge_nearby_pivots(highs, "high"),
        merge_nearby_pivots(lows, "low"),
    )


def passes_market_structure_filter(
    recent_df: pd.DataFrame,
    config: dict,
) -> tuple[bool, dict]:
    """
    60 根專用整體趨勢濾網。

    1. 最近 5 根的最低價，要高於前 10 根最高價指定 gap。
    2. 最新收盤價必須在 MA20 上方。
    3. MA20 最近 5 根必須向上，避免只因短暫反彈而入選。
    """
    base_zone_high = float(recent_df["High"].iloc[:BASE_ZONE_BARS].max())
    recent_zone_low = float(recent_df["Low"].iloc[-RECENT_ZONE_BARS:].min())
    required_recent_floor = base_zone_high * (1 + config["gap"])

    latest_close = float(recent_df["Close"].iloc[-1])
    latest_ma = float(recent_df["TrendMA"].iloc[-1])
    prior_ma = float(recent_df["TrendMA"].iloc[-1 - MA_SLOPE_BARS])

    platform_raised = recent_zone_low >= required_recent_floor
    above_ma = latest_close >= latest_ma
    ma_rising = latest_ma > prior_ma

    diagnostics = {
        "base_zone_high": base_zone_high,
        "recent_zone_low": recent_zone_low,
        "required_recent_floor": required_recent_floor,
        "latest_close": latest_close,
        "latest_ma": latest_ma,
        "ma_slope_pct": (latest_ma - prior_ma) / prior_ma if prior_ma else 0.0,
    }
    return platform_raised and above_ma and ma_rising, diagnostics


def identify_uptrend_logic(
    df: pd.DataFrame,
    symbol: str,
    tf_key: str,
    config: dict,
) -> list[dict]:
    """辨識最後 60 根內已確認完成的上漲波段。"""
    required_rows = ANALYSIS_BARS + TREND_MA
    if len(df) < required_rows:
        return []

    working_df = df.copy()
    working_df["TrendMA"] = working_df["Close"].rolling(TREND_MA).mean()
    recent_df = working_df.iloc[-ANALYSIS_BARS:].copy()

    passed, diagnostics = passes_market_structure_filter(recent_df, config)
    if not passed:
        return []

    highs, lows = find_pivots(recent_df)
    segments: list[dict] = []
    used_high_indices: set[int] = set()

    for low_index, low_price, low_time in lows:
        candidates = [
            high
            for high in highs
            if high[0] > low_index
            and high[0] not in used_high_indices
            and config["min_duration"] <= high[0] - low_index <= config["max_duration"]
        ]
        if not candidates:
            continue

        best_high = None
        best_rise = 0.0

        for high_index, high_price, high_time in candidates:
            rise_pct = (high_price - low_price) / low_price
            if rise_pct < config["rise"]:
                continue

            # 低點形成後到高點之前，不得再次跌破起始低點。
            middle_lows = recent_df["Low"].iloc[low_index + 1 : high_index]
            if not middle_lows.empty and float(middle_lows.min()) <= low_price:
                continue

            if rise_pct > best_rise:
                best_rise = rise_pct
                best_high = (high_index, high_price, high_time)

        if best_high is None:
            continue

        high_index, high_price, high_time = best_high
        bars_after_high = len(recent_df) - 1 - high_index
        if bars_after_high < COOLING_BARS:
            continue

        used_high_indices.add(high_index)
        segments.append(
            {
                "symbol": symbol,
                "timeframe": tf_key,
                "start_date": low_time.strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": high_time.strftime("%Y-%m-%d %H:%M:%S"),
                "start_label": low_time.strftime("%m-%d %H:%M"),
                "end_label": high_time.strftime("%m-%d %H:%M"),
                "start_price": round(low_price, 12),
                "end_price": round(high_price, 12),
                "rise_pct": round(best_rise, 4),
                "duration_bars": high_index - low_index,
                "bars_after_high": bars_after_high,
                "structure": {
                    "analysis_bars": ANALYSIS_BARS,
                    "trend_ma": TREND_MA,
                    "base_zone_high": round(diagnostics["base_zone_high"], 12),
                    "recent_zone_low": round(diagnostics["recent_zone_low"], 12),
                    "ma_slope_pct": round(diagnostics["ma_slope_pct"], 6),
                },
                "kline_data": [],
            }
        )

    return segments


def package_kline_data(df: pd.DataFrame) -> list[dict]:
    """打包最近 80 根，讓前 20 根只負責均線暖機，畫面顯示最後 60 根。"""
    package_df = df.iloc[-PACK_BARS:].copy()
    return [
        {
            "t": timestamp.strftime("%m-%d %H:%M"),
            "o": float(row["Open"]),
            "h": float(row["High"]),
            "l": float(row["Low"]),
            "c": float(row["Close"]),
            "v": float(row["Volume"]),
        }
        for timestamp, row in package_df.iterrows()
    ]


def main() -> None:
    symbols = get_all_binance_futures()
    all_results: list[dict] = []
    failed_requests = 0

    for symbol_index, symbol in enumerate(symbols, start=1):
        print(
            f"[{symbol_index}/{len(symbols)}] 分析中：{symbol:<18}",
            end="\r",
        )

        for tf_key, config in TF_CONFIG.items():
            df = fetch_klines(symbol, config["interval"])
            if df.empty:
                failed_requests += 1
                continue

            try:
                segments = identify_uptrend_logic(df, symbol, tf_key, config)
                if segments:
                    kline_package = package_kline_data(df)
                    for segment in segments:
                        segment["kline_data"] = kline_package
                        all_results.append(segment)
            except Exception as exc:
                failed_requests += 1
                print(f"\n⚠️ {symbol} {tf_key} 分析失敗：{exc}")

            time.sleep(0.05)

    output = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "settings": {
            "analysis_bars": ANALYSIS_BARS,
            "trend_ma": TREND_MA,
            "pivot_lookback": PIVOT_LOOKBACK,
            "cooling_bars": COOLING_BARS,
            "base_zone_bars": BASE_ZONE_BARS,
            "recent_zone_bars": RECENT_ZONE_BARS,
            "timeframes": TF_CONFIG,
        },
        "summary": {
            "symbols_scanned": len(symbols),
            "signals_found": len(all_results),
            "failed_requests": failed_requests,
        },
        "results": all_results,
    }

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    print(
        f"\n✅ 分析完成：找到 {len(all_results)} 組訊號，"
        f"失敗請求 {failed_requests} 次。"
    )
    print(f"輸出位置：{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
