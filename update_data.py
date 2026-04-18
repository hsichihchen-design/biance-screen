import pandas as pd
import requests
import json
import time
import ccxt
from datetime import datetime, timedelta

# ==========================================
# 核心策略參數設定 (1H 級別)
# ==========================================
MIN_RISE_PCT = 0.15      # 波段最小漲幅 15%
MIN_DURATION = 5         # 最少持續 5 小時 (5 根 K 棒)
LOOKBACK_PERIOD = 15     # 找尋局部高低點的視窗大小 (15 小時)
KLINE_LIMIT = 1500       # 抓取過去 1500 小時 (約 62.5 天) 的數據
MAX_SYMBOLS = 3000       # 取交易量前 150 名的標的 (避免流動性枯竭妖幣)

def get_binance_usdt_futures():
    """透過 CCXT 獲取並過濾幣安 U本位 永續合約代幣名單 (按交易量排序)"""
    print("正在透過 CCXT 獲取幣安 U 本位永續合約清單...")
    try:
        exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}
        })
        markets = exchange.load_markets()
        
        symbols_ccxt = []
        for symbol, market in markets.items():
            if (market.get('type') == 'swap' and 
                market.get('active', True) and 
                market.get('quote') == 'USDT'):
                symbols_ccxt.append(symbol)
                
        print(f"初步找到 {len(symbols_ccxt)} 個永續合約，正在獲取交易量進行過濾...")

        # 批次獲取所有 Ticker，極大化提升速度 (取代原本逐一 fetch_ticker 的迴圈)
        tickers = exchange.fetch_tickers(symbols_ccxt)
        volume_data = []
        
        for symbol in symbols_ccxt:
            if symbol in tickers:
                vol = tickers[symbol].get('quoteVolume', 0)
                # 提取原生的幣安 API 格式 (例如: 將 'BTC/USDT:USDT' 轉為 'BTCUSDT')
                raw_id = markets[symbol]['id']
                volume_data.append((raw_id, vol if vol is not None else 0))
                
        # 根據交易量 (quoteVolume) 降序排列
        volume_data.sort(key=lambda x: x[1], reverse=True)
        
        # 只保留流動性最佳的前 N 名標的
        top_symbols = [item[0] for item in volume_data[:MAX_SYMBOLS]]
        
        print(f"✅ 成功獲取並篩選出 {len(top_symbols)} 檔高流動性合約標的。")
        return top_symbols

    except Exception as e:
        print(f"獲取合約清單失敗: {e}")
        # 提供備用清單，確保 GitHub Actions 即使遇到 API 異常也不會完全當機
        print("使用備用藍籌合約清單繼續執行...")
        return [
            'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 
            'ADAUSDT', 'AVAXUSDT', 'DOGEUSDT', 'DOTUSDT', 'LINKUSDT'
        ]

def fetch_binance_klines(symbol, limit=KLINE_LIMIT):
    """抓取單一幣種的 1H K線數據 (保持輕量 requests 直連)"""
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit={limit}"
    try:
        res = requests.get(url, timeout=10).json()
        if isinstance(res, dict) and 'code' in res:
            return pd.DataFrame() 
        
        df = pd.DataFrame(res, columns=[
            'Open_time', 'Open', 'High', 'Low', 'Close', 'Volume', 
            'Close_time', 'Quote_volume', 'Trades', 'Taker_buy_base', 'Taker_buy_quote', 'Ignore'
        ])
        
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = df[col].astype(float)
            
        df['Open_time'] = pd.to_datetime(df['Open_time'], unit='ms') + timedelta(hours=8)
        df.set_index('Open_time', inplace=True)
        return df
    except Exception:
        return pd.DataFrame()

def check_ma_trend(df):
    """【宏觀趨勢濾網 - 1H級別】"""
    if len(df) < 120: return False

    latest_low = float(df['Low'].iloc[-1])
    old_zone_high = float(df['High'].iloc[-120:-90].max())
    if latest_low <= old_zone_high: return False

    current_zone_low = float(df['Low'].iloc[-30:].min())              
    zone_60_to_90_min = float(df['Low'].iloc[-90:-60].min())
    if current_zone_low < zone_60_to_90_min: return False 

    df['MA10'] = df['Close'].rolling(window=10).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    recent_df = df.iloc[-720:].dropna()
    if len(recent_df) < 60: return False

    days_below_ma60 = (recent_df['Low'] < recent_df['MA60']).sum()
    if days_below_ma60 > 120: return False  
        
    valid_days = ((recent_df['MA10'] > recent_df['MA60']) & (recent_df['MA20'] > recent_df['MA60'])).sum()
    ratio = valid_days / len(recent_df)
    
    return ratio >= 0.3

def identify_uptrend(df, symbol):
    """【微觀波段識別演算法 - 小時級別】"""
    if len(df) < LOOKBACK_PERIOD * 2: return []

    highs, lows = [], []
    for i in range(LOOKBACK_PERIOD, len(df) - LOOKBACK_PERIOD):
        window = df.iloc[i-LOOKBACK_PERIOD : i+LOOKBACK_PERIOD+1]
        
        if float(df['High'].iloc[i]) == float(window['High'].max()):
            highs.append((i, float(df['High'].iloc[i]), df.index[i]))
        if float(df['Low'].iloc[i]) == float(window['Low'].min()):
            lows.append((i, float(df['Low'].iloc[i]), df.index[i]))

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
            
            if rise_pct >= MIN_RISE_PCT and duration >= MIN_DURATION:
                segment_data = df.iloc[low_idx+1:high_idx]
                is_pure = True
                if len(segment_data) > 0:
                    min_in_segment = float(segment_data['Low'].min())
                    is_pure = min_in_segment > float(low_price)
                
                if is_pure and rise_pct > best_rise:
                    best_rise = rise_pct
                    best_high = (high_idx, high_price, high_time)
        
        if best_high:
            high_idx, high_price, high_time = best_high
            used_highs.add(high_idx)
            segments.append({
                'symbol': symbol,
                'start_date': low_time.strftime('%Y-%m-%d %H:00:00'),
                'end_date': high_time.strftime('%Y-%m-%d %H:00:00'),
                'start_price': round(float(low_price), 4), 
                'end_price': round(float(high_price), 4),
                'rise_pct': round(float(best_rise), 4),
                'duration_days': int(high_idx - low_idx) 
            })
    return segments

def main():
    symbols = get_binance_usdt_futures()
    if not symbols: return

    all_results = []
    failed_count = 0
    filtered_out_by_ma = 0
    filtered_out_by_timing = 0
    
    cooling_off_period = datetime.now() + timedelta(hours=8) - timedelta(hours=48)
    
    print("\n開始執行三重過濾 (宏觀均線 + 微觀波段 + 沉澱期濾網)...")
    total_symbols = len(symbols)
    
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/{total_symbols}] 分析中: {symbol}", end="\r")
        try:
            df = fetch_binance_klines(symbol)
            if df.empty: continue
                
            if not check_ma_trend(df):
                filtered_out_by_ma += 1
                continue
                
            segments = identify_uptrend(df, symbol)
            if segments:
                has_old_uptrend = any(datetime.strptime(seg['end_date'], '%Y-%m-%d %H:%M:%S') <= cooling_off_period for seg in segments)
                if has_old_uptrend:
                    all_results.extend(segments)
                else:
                    filtered_out_by_timing += 1
                    
        except Exception:
            failed_count += 1
            continue
            
        time.sleep(0.05)

    tw_time = datetime.utcnow() + timedelta(hours=8)
    output = {
        'last_updated': tw_time.strftime('%Y-%m-%d %H:%M:%S'),
        'total_segments_found': len(all_results),
        'results': all_results
    }
    
    with open('uptrend_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        
    print(f"\n✅ 幣安合約市場分析完成！")
    print(f"📊 淘汰報告：")
    print(f"   - {filtered_out_by_ma} 檔因【均線未達多頭標準】被淘汰。")
    print(f"   - {filtered_out_by_timing} 檔因【大漲發生在近 48 小時內 (籌碼未沉澱)】被淘汰。")
    print(f"🎯 最終找到 {len(set([r['symbol'] for r in all_results]))} 檔潛在標的，已存入 uptrend_results.json")

if __name__ == "__main__":
    main()
