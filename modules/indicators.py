import pandas as pd
import numpy as np

def calculate_ma(prices, period=50, ma_type='ema'):
    if len(prices) < period: return 0
    s = pd.Series(prices)
    if ma_type.lower() == 'ema':
        ma = s.ewm(span=period, adjust=False).mean()
    else:
        ma = s.rolling(window=period).mean()
    return float(ma.iloc[-1])

def calculate_rsi_value(prices, period=14):
    if len(prices) < period + 1: return 50.0
    s = pd.Series(prices)
    delta = s.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=period-1, adjust=False).mean()
    ma_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def calculate_bollinger_bands(prices, period=20, std_dev=2):
    if len(prices) < period: return 0, 0, 0
    s = pd.Series(prices)
    sma = s.rolling(window=period).mean()
    std = s.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return float(upper.iloc[-1]), float(sma.iloc[-1]), float(lower.iloc[-1])

def calculate_stoch_rsi_k(prices, rsi_period=14, stoch_period=14, k_window=3):
    if len(prices) < rsi_period + stoch_period: return 50
    s = pd.Series(prices)
    delta = s.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.ewm(com=rsi_period-1, adjust=False).mean()
    ma_down = down.ewm(com=rsi_period-1, adjust=False).mean()
    rsi = 100 - (100 / (1 + ma_up / ma_down))
    min_rsi = rsi.rolling(window=stoch_period).min()
    max_rsi = rsi.rolling(window=stoch_period).max()
    denom = max_rsi - min_rsi
    denom = denom.replace(0, 0.000001)
    stoch = ((rsi - min_rsi) / denom) * 100
    k = stoch.rolling(window=k_window).mean()
    return float(k.iloc[-1])

def calculate_adx(highs, lows, closes, period=14):
    if len(closes) < period * 2: return 0
    df = pd.DataFrame({'high': highs, 'low': lows, 'close': closes})
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift(1))
    df['tr2'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['up_move'] = df['high'] - df['high'].shift(1)
    df['down_move'] = df['low'].shift(1) - df['low']
    df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
    df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
    alpha = 1/period
    df['tr_s'] = df['tr'].ewm(alpha=alpha, adjust=False).mean()
    df['plus_dm_s'] = df['plus_dm'].ewm(alpha=alpha, adjust=False).mean()
    df['minus_dm_s'] = df['minus_dm'].ewm(alpha=alpha, adjust=False).mean()
    df['plus_di'] = 100 * (df['plus_dm_s'] / df['tr_s'])
    df['minus_di'] = 100 * (df['minus_dm_s'] / df['tr_s'])
    sum_di = df['plus_di'] + df['minus_di']
    sum_di = sum_di.replace(0, 0.000001)
    df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / sum_di
    df['adx'] = df['dx'].ewm(alpha=alpha, adjust=False).mean()
    return float(df['adx'].iloc[-1])

def check_volume_spike(volumes, period=20, multiplier=1.5):
    if len(volumes) < period + 1: return False, 0, 0
    prev_volumes = pd.Series(volumes[:-1])
    avg_vol = prev_volumes.rolling(window=period).mean().iloc[-1]
    current_vol = volumes[-1]
    if avg_vol == 0: return True, current_vol, 0
    target = avg_vol * multiplier
    is_spike = current_vol > target
    return is_spike, current_vol, target