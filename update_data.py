import json
import time
from datetime import datetime
from pathlib import Path

import ccxt
import pandas as pd
import requests

# ==========================================
# 60 根 K 棒：MA30 / MA45 / MA60 柔性趨勢篩選器
# ==========================================
# A 類：順勢延續
#   - 價格位於 MA30 附近或上方
#   - MA30 / MA45 / MA60 維持大致多頭排列
#   - 允許均線之間有小幅交錯，不因「壓線」立刻淘汰
#
# B 類：均線壓回整理
#   - 價格可落到 MA30 或 MA45 下方
#   - 但仍需守在上升中的 MA60 容許帶附近
#   - 近期必須出現回穩或重新轉強跡象
#
# rise：局部低點到局部高點的最低漲幅
# gap：最近平台相對分析區前段平台至少抬高多少
# max_pullback：從已確認高點回落到最新收盤的最大幅度
# ma60_min_slope：MA60 相對 10 根前的最低上升幅度
# line_tolerance_min/max：均線壓線的最小／最大容許幅度
TF_CONFIG = {
    "5m": {
        "interval": "5m",
        "rise": 0.025,
        "gap": 0.012,
        "min_duration": 3,
        "max_duration": 30,
        "max_pullback": 0.10,
        "ma60_min_slope": 0.000,
        "line_tolerance_min": 0.003,
        "line_tolerance_max": 0.015,
    },
    "15m": {
        "interval": "15m",
        "rise": 0.045,
        "gap": 0.025,
        "min_duration": 3,
        "max_duration": 30,
        "max_pullback": 0.12,
        "ma60_min_slope": 0.001,
        "line_tolerance_min": 0.004,
        "line_tolerance_max": 0.018,
    },
    "1h": {
        "interval": "1h",
        "rise": 0.070,
        "gap": 0.040,
        "min_duration": 3,
        "max_duration": 30,
        "max_pullback": 0.15,
        "ma60_min_slope": 0.002,
        "line_tolerance_min": 0.006,
        "line_tolerance_max": 0.020,
    },
    "4h": {
        "interval": "4h",
        "rise": 0.100,
        "gap": 0.060,
        "min_duration": 3,
        "max_duration": 35,
        "max_pullback": 0.20,
        "ma60_min_slope": 0.003,
        "line_tolerance_min": 0.008,
        "line_tolerance_max": 0.025,
    },
    "1d": {
        "interval": "1d",
        "rise": 0.200,
        "gap": 0.080,
        "min_duration": 5,
        "max_duration": 40,
        "max_pullback": 0.25,
        "ma60_min_slope": 0.005,
        "line_tolerance_min": 0.010,
        "line_tolerance_max": 0.030,
    },
}

# ==========================================
# 結構判斷參數
# ==========================================
ANALYSIS_BARS = 60
MA_FAST = 30
MA_MID = 45
MA_LONG = 60
ATR_PERIOD = 14

MA30_SLOPE_BARS = 5
MA45_SLOPE_BARS = 8
MA60_SLOPE_BARS = 10

# 使用區間分位數比較舊平台與新平台，降低單根影線干擾。
BASE_ZONE_BARS = 10
RECENT_ZONE_BARS = 10
BASE_ZONE_QUANTILE = 0.80
RECENT_ZONE_QUANTILE = 0.20

# 左右各 4 根，共 9 根確認一個局部轉折。
PIVOT_LOOKBACK = 4
PIVOT_MERGE_DISTANCE = 2
COOLING_BARS = 2

# 均線允許約 1.5% 的柔性交錯，不要求每一刻都嚴格 MA30 > MA45 > MA60。
MA_ALIGNMENT_TOLERANCE = 0.015

# A 類：MA30 可小幅轉平或下降，但不可明顯轉弱。
A_MA30_MAX_DECLINE = 0.010
A_NEAR_MA60_RATIO = 0.80

# B 類：MA45 可短暫走平／微降，但 MA60 必須上升。
B_MA45_MAX_DECLINE = 0.015
B_NEAR_MA60_RATIO = 0.65
B_MAX_CONSECUTIVE_BELOW_MA60 = 2
RECOVERY_LOOKBACK = 3

# 容許帶採 ATR 自動調整，並受各週期 min/max 約束。
ATR_TOLERANCE_MULTIPLIER = 0.50

# 60 根顯示 + 60 根 MA60 暖機。
PACK_BARS = ANALYSIS_BARS + MA_LONG
FETCH_LIMIT = 180

OUTPUT_FILE = Path(__file__).resolve().parent / "uptrend_results.json"

session = requests.Session()
session.headers.update({"User-Agent": "binance-screen/ma30-ma45-ma60"})


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
    """取得已收盤 K 線；遇到暫時性錯誤會重試。"""
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
            numeric_columns = [
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
                "Close_time",
            ]
            df[numeric_columns] = df[numeric_columns].apply(
                pd.to_numeric, errors="coerce"
            )
            df.dropna(subset=numeric_columns, inplace=True)

            # 排除尚未收盤的最後一根 K 棒。
            now_ms = int(time.time() * 1000)
            df = df[df["Close_time"] <= now_ms].copy()

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
    """合併距離過近的同類轉折，只保留更極端的價格。"""
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
    """使用左右各 4 根 K 棒確認局部高點與局部低點。"""
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


def calculate_atr(frame: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """計算 ATR，作為不同標的、不同週期的動態壓線容許帶。"""
    previous_close = frame["Close"].shift(1)
    true_range = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - previous_close).abs(),
            (frame["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period).mean()


def max_consecutive_true(values: pd.Series) -> int:
    """回傳布林序列中最長連續 True 次數。"""
    maximum = 0
    current = 0
    for value in values.fillna(False):
        if bool(value):
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def get_market_diagnostics(recent_df: pd.DataFrame, config: dict) -> dict:
    """計算平台、MA30/45/60、ATR 容許帶與近期恢復訊號。"""
    base_zone_reference = float(
        recent_df["Close"].iloc[:BASE_ZONE_BARS].quantile(BASE_ZONE_QUANTILE)
    )
    recent_zone_reference = float(
        recent_df["Close"].iloc[-RECENT_ZONE_BARS:].quantile(
            RECENT_ZONE_QUANTILE
        )
    )
    required_recent_floor = base_zone_reference * (1 + config["gap"])

    latest_close = float(recent_df["Close"].iloc[-1])
    ma30 = float(recent_df["MA30"].iloc[-1])
    ma45 = float(recent_df["MA45"].iloc[-1])
    ma60 = float(recent_df["MA60"].iloc[-1])
    atr14 = float(recent_df["ATR14"].iloc[-1])

    ma30_prior = float(recent_df["MA30"].iloc[-1 - MA30_SLOPE_BARS])
    ma45_prior = float(recent_df["MA45"].iloc[-1 - MA45_SLOPE_BARS])
    ma60_prior = float(recent_df["MA60"].iloc[-1 - MA60_SLOPE_BARS])

    ma30_slope_pct = (ma30 - ma30_prior) / ma30_prior if ma30_prior else 0.0
    ma45_slope_pct = (ma45 - ma45_prior) / ma45_prior if ma45_prior else 0.0
    ma60_slope_pct = (ma60 - ma60_prior) / ma60_prior if ma60_prior else 0.0

    atr_tolerance_pct = (
        ATR_TOLERANCE_MULTIPLIER * atr14 / latest_close if latest_close else 0.0
    )
    line_tolerance_pct = min(
        max(atr_tolerance_pct, config["line_tolerance_min"]),
        config["line_tolerance_max"],
    )

    ma30_floor = ma30 * (1 - line_tolerance_pct)
    ma45_floor = ma45 * (1 - line_tolerance_pct)
    ma60_floor = ma60 * (1 - line_tolerance_pct)

    recent_ten = recent_df.iloc[-10:]
    recent_ma60_floor = recent_ten["MA60"] * (1 - line_tolerance_pct)
    close_near_ma60_ratio = float(
        (recent_ten["Close"] >= recent_ma60_floor).mean()
    )
    below_ma60_band = recent_ten["Close"] < recent_ma60_floor
    max_consecutive_below_ma60 = max_consecutive_true(below_ma60_band)

    previous_closes = recent_df["Close"].iloc[-1 - RECOVERY_LOOKBACK : -1]
    last_three_closes = recent_df["Close"].iloc[-3:]
    sequential_recovery = bool(
        len(last_three_closes) == 3
        and last_three_closes.iloc[-1]
        > last_three_closes.iloc[-2]
        > last_three_closes.iloc[-3]
    )
    recovery_signal = bool(
        latest_close >= float(previous_closes.max())
        or latest_close >= ma30_floor
        or sequential_recovery
    )

    soft_ma30_above_ma45 = ma30 >= ma45 * (1 - MA_ALIGNMENT_TOLERANCE)
    soft_ma45_above_ma60 = ma45 >= ma60 * (1 - MA_ALIGNMENT_TOLERANCE)

    return {
        "base_zone_reference": base_zone_reference,
        "recent_zone_reference": recent_zone_reference,
        "required_recent_floor": required_recent_floor,
        "platform_raised": recent_zone_reference >= required_recent_floor,
        "latest_close": latest_close,
        "ma30": ma30,
        "ma45": ma45,
        "ma60": ma60,
        "atr14": atr14,
        "line_tolerance_pct": line_tolerance_pct,
        "ma30_floor": ma30_floor,
        "ma45_floor": ma45_floor,
        "ma60_floor": ma60_floor,
        "ma30_slope_pct": ma30_slope_pct,
        "ma45_slope_pct": ma45_slope_pct,
        "ma60_slope_pct": ma60_slope_pct,
        "ma60_rising": ma60_slope_pct >= config["ma60_min_slope"],
        "soft_ma30_above_ma45": soft_ma30_above_ma45,
        "soft_ma45_above_ma60": soft_ma45_above_ma60,
        "close_near_ma60_ratio": close_near_ma60_ratio,
        "max_consecutive_below_ma60": max_consecutive_below_ma60,
        "recovery_signal": recovery_signal,
    }


def classify_signal(
    high_price: float,
    diagnostics: dict,
    config: dict,
) -> tuple[str | None, str | None, dict]:
    """依價格相對 MA30/45/60 的位置分成 A 或 B。"""
    latest_close = diagnostics["latest_close"]
    ma30_slope_pct = diagnostics["ma30_slope_pct"]
    ma45_slope_pct = diagnostics["ma45_slope_pct"]
    close_near_ma60_ratio = diagnostics["close_near_ma60_ratio"]

    pullback_pct = max(0.0, (high_price - latest_close) / high_price)

    # A：價格在 MA30 容許帶附近或上方，均線大致維持多頭排列。
    continuation_structure = bool(
        latest_close >= diagnostics["ma30_floor"]
        and diagnostics["soft_ma30_above_ma45"]
        and diagnostics["soft_ma45_above_ma60"]
        and ma30_slope_pct >= -A_MA30_MAX_DECLINE
        and close_near_ma60_ratio >= A_NEAR_MA60_RATIO
        and pullback_pct <= config["max_pullback"]
    )

    # B：價格可以壓到 MA45、甚至稍微壓到 MA60，但不可長時間失守。
    pullback_structure = bool(
        latest_close >= diagnostics["ma60_floor"]
        and diagnostics["soft_ma45_above_ma60"]
        and ma45_slope_pct >= -B_MA45_MAX_DECLINE
        and close_near_ma60_ratio >= B_NEAR_MA60_RATIO
        and diagnostics["max_consecutive_below_ma60"]
        <= B_MAX_CONSECUTIVE_BELOW_MA60
        and diagnostics["recovery_signal"]
        and pullback_pct <= config["max_pullback"]
    )

    extra = {
        "pullback_pct": pullback_pct,
        "continuation_structure": continuation_structure,
        "pullback_structure": pullback_structure,
    }

    if continuation_structure:
        return "A", "順勢延續", extra
    if pullback_structure:
        return "B", "均線壓回", extra
    return None, None, extra


def identify_uptrend_logic(
    df: pd.DataFrame,
    symbol: str,
    tf_key: str,
    config: dict,
) -> list[dict]:
    """辨識最後 60 根內的主升段，再依 MA30/45/60 分類目前狀態。"""
    required_rows = ANALYSIS_BARS + MA_LONG
    if len(df) < required_rows:
        return []

    working_df = df.copy()
    working_df["MA30"] = working_df["Close"].rolling(MA_FAST).mean()
    working_df["MA45"] = working_df["Close"].rolling(MA_MID).mean()
    working_df["MA60"] = working_df["Close"].rolling(MA_LONG).mean()
    working_df["ATR14"] = calculate_atr(working_df, ATR_PERIOD)
    recent_df = working_df.iloc[-ANALYSIS_BARS:].copy()

    if recent_df[["MA30", "MA45", "MA60", "ATR14"]].isna().any().any():
        return []

    diagnostics = get_market_diagnostics(recent_df, config)

    # 兩種型態都必須先符合：價格平台已抬高、MA60 仍上升。
    if not diagnostics["platform_raised"] or not diagnostics["ma60_rising"]:
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
            and config["min_duration"]
            <= high[0] - low_index
            <= config["max_duration"]
        ]
        if not candidates:
            continue

        best_high = None
        best_rise = 0.0

        for high_index, high_price, high_time in candidates:
            rise_pct = (high_price - low_price) / low_price
            if rise_pct < config["rise"]:
                continue

            # 低點形成後到高點以前，不得再次跌破起始低點。
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

        signal_type, signal_name, classification = classify_signal(
            high_price=high_price,
            diagnostics=diagnostics,
            config=config,
        )
        if signal_type is None:
            continue

        used_high_indices.add(high_index)
        segments.append(
            {
                "symbol": symbol,
                "timeframe": tf_key,
                "signal_type": signal_type,
                "signal_name": signal_name,
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
                    "ma_fast": MA_FAST,
                    "ma_mid": MA_MID,
                    "ma_long": MA_LONG,
                    "base_zone_reference": round(
                        diagnostics["base_zone_reference"], 12
                    ),
                    "recent_zone_reference": round(
                        diagnostics["recent_zone_reference"], 12
                    ),
                    "latest_close": round(diagnostics["latest_close"], 12),
                    "ma30": round(diagnostics["ma30"], 12),
                    "ma45": round(diagnostics["ma45"], 12),
                    "ma60": round(diagnostics["ma60"], 12),
                    "atr14": round(diagnostics["atr14"], 12),
                    "line_tolerance_pct": round(
                        diagnostics["line_tolerance_pct"], 6
                    ),
                    "ma30_slope_pct": round(
                        diagnostics["ma30_slope_pct"], 6
                    ),
                    "ma45_slope_pct": round(
                        diagnostics["ma45_slope_pct"], 6
                    ),
                    "ma60_slope_pct": round(
                        diagnostics["ma60_slope_pct"], 6
                    ),
                    "soft_ma30_above_ma45": diagnostics[
                        "soft_ma30_above_ma45"
                    ],
                    "soft_ma45_above_ma60": diagnostics[
                        "soft_ma45_above_ma60"
                    ],
                    "close_near_ma60_ratio": round(
                        diagnostics["close_near_ma60_ratio"], 4
                    ),
                    "max_consecutive_below_ma60": diagnostics[
                        "max_consecutive_below_ma60"
                    ],
                    "recovery_signal": diagnostics["recovery_signal"],
                    "pullback_pct": round(classification["pullback_pct"], 4),
                },
                "kline_data": [],
            }
        )

    return segments


def package_kline_data(df: pd.DataFrame) -> list[dict]:
    """打包最近 120 根；前 60 根負責 MA60 暖機。"""
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

    type_a_count = sum(1 for item in all_results if item["signal_type"] == "A")
    type_b_count = sum(1 for item in all_results if item["signal_type"] == "B")

    output = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "settings": {
            "analysis_bars": ANALYSIS_BARS,
            "ma_fast": MA_FAST,
            "ma_mid": MA_MID,
            "ma_long": MA_LONG,
            "pivot_lookback": PIVOT_LOOKBACK,
            "cooling_bars": COOLING_BARS,
            "base_zone_bars": BASE_ZONE_BARS,
            "recent_zone_bars": RECENT_ZONE_BARS,
            "timeframes": TF_CONFIG,
        },
        "summary": {
            "symbols_scanned": len(symbols),
            "signals_found": len(all_results),
            "type_a_signals": type_a_count,
            "type_b_signals": type_b_count,
            "failed_requests": failed_requests,
        },
        "results": all_results,
    }

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)

    print(
        f"\n✅ 分析完成：共 {len(all_results)} 組訊號 "
        f"（A {type_a_count}／B {type_b_count}），"
        f"失敗請求 {failed_requests} 次。"
    )
    print(f"輸出位置：{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
