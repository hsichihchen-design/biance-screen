import pandas as pd
import requests
import json
import time
from datetime import datetime, timedelta

# ==========================================
# 核心策略參數設定 (1H 級別)
# ==========================================
MIN_RISE_PCT = 0.15      # 波段最小漲幅 15%
MIN_DURATION = 5         # 最少持續 5 小時 (5 根 K 棒)
LOOKBACK_PERIOD = 15     # 找尋局部高低點的視窗大小 (15 小時)
KLINE_LIMIT = 1500       # 抓取過去 1500 小時 (約 62.5 天) 的數據

def get_binance_usdt_futures():
    """獲取幣安所有 U本位 永續合約代幣名單"""
    print("正在獲取幣安 U 本位永續合約清單...")
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        res = requests.get(url, timeout=10).json()
        # 篩選：永續合約 + 結算為USDT + 交易中
        symbols = [
            s['symbol'] for s in res['symbols'] 
            if s['contractType'] == 'PERPETUAL' 
            and s['quoteAsset'] == 'USDT' 
            and s['status'] == 'TRADING'
        ]
        print(f"共找到 {len(symbols)} 檔 U 本位合約。")
        return symbols
    except Exception as e:
        print(f"獲取合約清單失敗: {e}")
        return []

def fetch_binance_klines(symbol, limit=KLINE_LIMIT):
    """抓取單一幣種的 1H K線數據"""
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&limit={limit}"
    try:
        res = requests.get(url, timeout=10).json()
        if isinstance(res, dict) and 'code' in res:
            return pd.DataFrame() # API 錯誤
        
        # 幣安 API 回傳格式: [Open time, Open, High, Low, Close, Volume, Close time, Quote asset volume, Number of trades, ...]
        df = pd.DataFrame(res, columns=[
            'Open_time', 'Open', 'High', 'Low', 'Close', 'Volume', 
            'Close_time', 'Quote_volume', 'Trades', 'Taker_buy_base', 'Taker_buy_quote', 'Ignore'
        ])
        
        # 轉換型別
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = df[col].astype(float)
            
        # 處理時間 (將毫秒級時間戳轉為 UTC+8)
        df['Open_time'] = pd.to_datetime(df['Open_time'], unit='ms') + timedelta(hours=8)
        df.set_index('Open_time', inplace=True)
        return df
    except Exception as e:
        return pd.DataFrame()

def check_ma_trend(df):
    """【宏觀趨勢濾網 - 1H級別調整版】"""
    if len(df) < 120: 
        return False

    # 1. 最新 K 棒強勢突破 (站上 90-120 小時前的高點壓力區)
    latest_low = float(df['Low'].iloc[-1])
    old_zone_high = float(df['High'].iloc[-120:-90].max())
    if latest_low <= old_zone_high:
        return False

    # 2. 區間底部支撐墊高保護 (近 30 小時 vs 60-90 小時)
    current_zone_low = float(df['Low'].iloc[-30:].min())              
    zone_60_to_90_min = float(df['Low'].iloc[-90:-60].min())
    if current_zone_low < zone_60_to_90_min:
        return False # 允許關閉此濾網，目前設定為嚴格底底高

    # 3. 均線計算 (10H, 20H, 60H)
    df['MA10'] = df['Close'].rolling(window=30).mean()
    df['MA20'] = df['Close'].rolling(window=45).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    # 取最近 720 小時 (約一個月) 的資料作多頭排列檢驗
    recent_df = df.iloc[-720:].dropna()
    if len(recent_df) < 60:
        return False

    # 跌破 60MA 容忍度 (在近 720 小時內，跌破 60H 均線的次數不能超過 120 小時)
    days_below_ma60 = (recent_df['Low'] < recent_df['MA60']).sum()
    if days_below_ma60 > 120:
        return False  
        
    # 多頭排列比例檢驗 (10MA > 60MA 且 20MA > 60MA)
    valid_days = ((recent_df['MA10'] > recent_df['MA60']) & (recent_df['MA20'] > recent_df['MA60'])).sum()
    ratio = valid_days / len(recent_df)
    
    return ratio >= 0.3

def identify_uptrend(df, symbol):
    """【微觀波段識別演算法 - 小時級別】"""
    if len(df) < LOOKBACK_PERIOD * 2:
        return []

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
                
                if is_pure:
                    if rise_pct > best_rise:
                        best_rise = rise_pct
                        best_high = (high_idx, high_price, high_time)
        
        if best_high:
            high_idx, high_price, high_time = best_high
            used_highs.add(high_idx)
            segments.append({
                'symbol': symbol,
                'start_date': low_time.strftime('%Y-%m-%d %H:00:00'),
                'end_date': high_time.strftime('%Y-%m-%d %H:00:00'),
                'start_price': round(float(low_price), 4), # 幣圈精確度需提升至小數點後 4 位
                'end_price': round(float(high_price), 4),
                'rise_pct': round(float(best_rise), 4),
                'duration_days': int(high_idx - low_idx) # 實為 duration_hours
            })
    return segments

def main():
    symbols = get_binance_usdt_futures()
    if not symbols:
        return

    all_results = []
    failed_count = 0
    filtered_out_by_ma = 0
    filtered_out_by_timing = 0
    
    # 沉澱期濾網：判斷波段結束日是否在 48 小時之前 (將之前的 60天/15天 縮放至合適的 H 級別)
    cooling_off_period = datetime.now() + timedelta(hours=8) - timedelta(hours=48)
    
    print("\n開始執行三重過濾 (宏觀均線 + 微觀波段 + 沉澱期濾網)...")
    total_symbols = len(symbols)
    
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/{total_symbols}] 分析中: {symbol}", end="\r")
        try:
            # 1. 獲取數據
            df = fetch_binance_klines(symbol)
            if df.empty:
                continue
                
            # 2. 宏觀趨勢過濾
            if not check_ma_trend(df):
                filtered_out_by_ma += 1
                continue
                
            # 3. 微觀波段識別
            segments = identify_uptrend(df, symbol)
            if segments:
                # 4. 時間濾網 (確保至少有一個暴漲波段發生在 48 小時前，表示籌碼已沉澱)
                has_old_uptrend = any(datetime.strptime(seg['end_date'], '%Y-%m-%d %H:%M:%S') <= cooling_off_period for seg in segments)
                
                if has_old_uptrend:
                    all_results.extend(segments)
                else:
                    filtered_out_by_timing += 1
                    
        except Exception as e:
            failed_count += 1
            continue
            
        # 遵守幣安 REST API 的頻率限制 (每分鐘 1200 權重，單檔拉取極低，但給予微小緩衝)
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
    if failed_count > 0:
        print(f"⚠️ 有 {failed_count} 檔在計算時發生例外。")

if __name__ == "__main__":
    main()