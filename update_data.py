import pandas as pd
import requests
import json
import time
import ccxt
from datetime import datetime, timedelta

# ==========================================
# 多週期戰略參數矩陣 (已改為 4h / 25%)
# gap: 最新一根最低點，必須高於第 180 根最高點的百分比
# ==========================================
TF_CONFIG = {
    '3m':  {'rise': 0.03, 'interval': '3m',  'gap': 0.03}, 
    '15m': {'rise': 0.07, 'interval': '15m', 'gap': 0.10}, 
    '1h':  {'rise': 0.1, 'interval': '1h',  'gap': 0.15},  
    '4h':  {'rise': 0.15, 'interval': '4h',  'gap': 0.20}   # 改 8h -> 4h, 漲幅 25%
}

# ==========================================
# 核心常數 (升級為 180 根基準)
# ==========================================
ANALYSIS_BARS = 180      # 統一分析最後 180 根 K 棒
LOOKBACK_PERIOD = 10     
MIN_DURATION = 3         
COOLING_BARS = 30        

session = requests.Session()

def get_all_binance_futures():
    print("正在透過 CCXT 獲取全市場 U 本位永續合約清單...")
    try:
        exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
        markets = exchange.load_markets()
        symbols = [m['id'] for m in markets.values() if m.get('type') == 'swap' and m.get('quote') == 'USDT' and m.get('active', True)]
        print(f"✅ 成功獲取 {len(symbols)} 檔合約標的。")
        return symbols
    except Exception as e:
        print(f"獲取清單失敗: {e}")
        return ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']

def fetch_klines(symbol, interval, limit=300):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = session.get(url, timeout=5).json()
        if isinstance(res, dict) and 'code' in res: return pd.DataFrame()
        df = pd.DataFrame(res, columns=['Open_time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close_time', 'Quote_volume', 'Trades', 'Taker_buy_base', 'Taker_buy_quote', 'Ignore'])
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']: df[col] = df[col].astype(float)
        df['Open_time'] = pd.to_datetime(df['Open_time'], unit='ms') + timedelta(hours=8)
        df.set_index('Open_time', inplace=True)
        return df
    except Exception: return pd.DataFrame()

def identify_uptrend_logic(df, symbol, tf_key, config):
    if len(df) < ANALYSIS_BARS: return []
    df['MA60'] = df['Close'].rolling(window=60).mean()
    recent_df = df.iloc[-ANALYSIS_BARS:].copy()
    
    # 階梯式墊高濾網：最新最低點不能低於第 180 根的最高點 (可含 gap 空間)
    latest_low = float(recent_df['Low'].iloc[-1])
    oldest_high = float(recent_df['High'].iloc[0])
    if latest_low < oldest_high * (1 + config['gap']): return []
    
    # 趨勢濾網
    if recent_df['Close'].iloc[-1] < recent_df['MA60'].iloc[-1]: return []

    highs, lows = [], []
    for i in range(LOOKBACK_PERIOD, len(recent_df) - LOOKBACK_PERIOD):
        window = recent_df.iloc[i-LOOKBACK_PERIOD : i+LOOKBACK_PERIOD+1]
        if float(recent_df['High'].iloc[i]) == float(window['High'].max()):
            highs.append((i, float(recent_df['High'].iloc[i]), recent_df.index[i]))
        if float(recent_df['Low'].iloc[i]) == float(window['Low'].min()):
            lows.append((i, float(recent_df['Low'].iloc[i]), recent_df.index[i]))

    segments = []
    used_highs = set()
    for low_idx, low_price, low_time in lows:
        candidates = [h for h in highs if h[0] > low_idx and h[0] not in used_highs]
        if not candidates: continue
        best_high = None
        best_rise = 0
        for high_idx, high_price, high_time in candidates:
            rise_pct = (high_price - low_price) / low_price
            duration = high_idx - low_idx
            if rise_pct >= config['rise'] and duration >= MIN_DURATION:
                segment_data = recent_df.iloc[low_idx+1:high_idx]
                if (len(segment_data) == 0 or float(segment_data['Low'].min()) > float(low_price)) and rise_pct > best_rise:
                    best_rise = rise_pct
                    best_high = (high_idx, high_price, high_time)
        
        if best_high and (len(recent_df) - 1 - best_high[0]) >= COOLING_BARS:
            used_highs.add(best_high[0])
            segments.append({
                'symbol': symbol, 'timeframe': tf_key,
                'start_date': low_time.strftime('%Y-%m-%d %H:%M:%S'),
                'end_date': best_high[2].strftime('%Y-%m-%d %H:%M:%S'),
                'rise_pct': round(float(best_rise), 4),
                'kline_data': [] # 待填充
            })
    return segments

def main():
    symbols = get_all_binance_futures()
    all_results = []
    total_symbols = len(symbols)
    
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/{total_symbols}] 分析與打包中: {symbol}                ", end="\r")
        for tf_key, config in TF_CONFIG.items():
            try:
                df = fetch_klines(symbol, config['interval'])
                if df.empty: continue
                segments = identify_uptrend_logic(df, symbol, tf_key, config)
                if segments:
                    # 打包 240 根 (180 分析區 + 60 歷史緩衝區)，確保 MA60 畫滿
                    pack_df = df.iloc[-240:].copy() 
                    k_package = [{'t': t.strftime('%m-%d %H:%M'), 'o': r['Open'], 'h': r['High'], 'l': r['Low'], 'c': r['Close'], 'v': r['Volume']} for t, r in pack_df.iterrows()]
                    for seg in segments:
                        seg['kline_data'] = k_package
                        all_results.append(seg)
            except Exception: continue
            time.sleep(0.05)

    output = {'last_updated': (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S'), 'results': all_results}
    with open('uptrend_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 分析完成！找到 {len(all_results)} 組符合結構之標的。")

if __name__ == "__main__":
    main()