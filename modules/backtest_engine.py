import pandas as pd
import asyncio
import io
import traceback
import time
import bisect
import numpy as np
from decimal import Decimal, ROUND_DOWN
from modules.database import db
from modules.mock_exchange import MockExchange
from languages import TRANSLATIONS

# 导入策略类
from modules.strategies.fvg import FVGStrategy
from modules.strategies.grid_dca import GridDCAStrategy
from modules.strategies.coffin import CoffinStrategy
from modules.strategies import get_strategy_class

# 导入公共指标库
from modules.indicators import (
    calculate_ma, calculate_rsi_value, calculate_bollinger_bands,
    calculate_stoch_rsi_k, calculate_adx, check_volume_spike
)

# ================= 辅助函数 =================

def resample_candles(df_15m, target_tf):
    """
    将 K 线数据重采样为大周期
    """
    tf_map = {'1h': '1h', '4h': '4h', '1d': '1d', '4H': '4h', '1D': '1d'}
    rule = tf_map.get(target_tf)
    if not rule: return df_15m
    
    df = df_15m.copy()
    if 'dt' not in df.columns:
        df['dt'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('dt', inplace=True)
    
    # 确保 volume 也被正确聚合
    resampled = df.resample(rule).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'timestamp': 'last'
    }).dropna()
    
    resampled = resampled.reset_index(drop=True)
    return resampled

def prepare_fast_lookup(resampled_df):
    """
    将 DataFrame 转换为列表，方便在循环中极速查找
    """
    resampled_df = resampled_df.sort_values('timestamp')
    ts_index = resampled_df['timestamp'].values # numpy array 用于二分查找
    closes = resampled_df['close'].tolist()
    # 缓存所有列数据 [ts, open, high, low, close, volume]
    full_data = resampled_df[['timestamp','open','high','low','close','volume']].values.tolist()
    return ts_index, closes, full_data

# 模拟获取 FVG
async def _update_fvgs_mock(strategy, exchange, symbol):
    timeframes = ['1h', '4h'] 
    tasks = []
    for tf in timeframes:
        tasks.append(strategy.find_fvgs(exchange, symbol, tf))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_fvgs = []
    for res in results:
        if isinstance(res, list):
            all_fvgs.extend(res)
    return all_fvgs

def check_rsi_conditions_mock(rsi_configs, prices_dict):
    if not rsi_configs: return True, ""
    active_conds = [c for c in rsi_configs if c.get('enabled')]
    if not active_conds: return True, ""

    status_details = []
    all_passed = True

    for c in active_conds:
        tf = c['tf']
        try: threshold = float(c['val'])
        except: continue
        
        closes = prices_dict.get(tf, [])
        if len(closes) < 15: continue
        
        rsi_val = calculate_rsi_value(closes)
        op = c['op']
        passed = (rsi_val < threshold) if op == '<' else (rsi_val > threshold)
        
        icon = "✅" if passed else "❌"
        status_details.append(f"{tf}({rsi_val:.1f}{op}{int(threshold)}){icon}")
        if not passed: all_passed = False
            
    return all_passed, " ".join(status_details)

# ================= 回测主逻辑 =================

async def run_backtest(bot_id, file_content):
    try:
        # --- 1. 数据加载 ---
        print(f"📂 开始读取回测文件...")
        df = pd.read_csv(io.BytesIO(file_content))
        df.columns = [c.lower().strip() for c in df.columns]
        rename_map = {'time': 'timestamp', 'date': 'timestamp', 'vol': 'volume'}
        df.rename(columns=rename_map, inplace=True)
        
        if df['timestamp'].iloc[0] < 10000000000:
             df['timestamp'] = df['timestamp'] * 1000
             
        # --- 2. 初始化环境 ---
        bot = await db.get_bot_full_data(bot_id)
        if not bot: raise Exception("Bot not found")
        
        cfg = bot.get('config', {})
        state = bot.get('state', {})
        strategy_type = bot.get('strategy_type', 'fvg')
        symbol = cfg.get('symbol', 'BTC/USDT')
        
        # 清除僵尸状态
        state['position_amt'] = 0
        state['avg_price'] = 0
        state['total_cost'] = 0
        state['current_profit'] = 0
        state['last_close_time'] = 0
        state['balance'] = float(cfg.get('capital', 1000.0))
        state['orders'] = [] 
        state['is_trailing_active'] = False
        state['highest_price_seen'] = 0.0
        state['lowest_price_seen'] = 0.0
        
        # 清除策略特定状态
        for k in ['stage', 'breakout_price', 'breakout_dir', 'stop_loss_price', 
                  'extreme_price', 'coffin_5m', 'coffin_15m', 'range_top', 
                  'range_bottom', 'last_level_idx', 'initial_base_price', 'current_so_index']:
            state.pop(k, None)
            
        user_lang = bot.get('language', 'zh-CN')
        def t(key): return TRANSLATIONS.get(user_lang, TRANSLATIONS['zh-CN']).get(key, key)
            
        current_backtest_ts = 0.0 
        def mock_now(): return current_backtest_ts

        # 实例化策略
        StrategyClass = get_strategy_class(strategy_type)
        if not StrategyClass:
             if strategy_type == 'grid_dca': StrategyClass = GridDCAStrategy
             elif strategy_type == 'coffin': StrategyClass = CoffinStrategy
             else: StrategyClass = FVGStrategy
        strategy = StrategyClass(cfg, t_func=t, now_func=mock_now)

        exchange = MockExchange(df)
        
        async with db.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM trade_logs WHERE bot_id = %s", (bot_id,))

        print(f"🚀 Bot {bot_id} 回测开始，Strategy: {strategy_type}, Rows: {len(df)}")
        
        # === [性能优化核心] 预先计算所有大周期数据 ===
        print("⏳ 正在预计算大周期数据 (1h/4h/1d)...这可能需要几秒钟")
        df['dt'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        df_1h_full = resample_candles(df, '1h')
        df_4h_full = resample_candles(df, '4h')
        df_1d_full = resample_candles(df, '1d')

        # 转换为查表结构
        ts_1h, closes_1h, data_1h = prepare_fast_lookup(df_1h_full)
        ts_4h, closes_4h, data_4h = prepare_fast_lookup(df_4h_full)
        ts_1d, closes_1d, data_1d = prepare_fast_lookup(df_1d_full)
        print("✅ 预计算完成，开始高速回测循环...")

        start_loop_index = 2000 if len(df) > 2000 else 100
        
        last_fvgs = []
        
        # === 极速循环开始 ===
        # [关键修复] 使用 tolist() 将 NumPy 数组转为 Python 列表
        # 这解决了 "int64 is not JSON serializable" 的报错
        ts_arr = df['timestamp'].values.tolist()
        open_arr = df['open'].values.tolist()
        high_arr = df['high'].values.tolist()
        low_arr = df['low'].values.tolist()
        close_arr = df['close'].values.tolist()
        vol_arr = df['volume'].values.tolist()
        
        for i in range(start_loop_index, len(df)):
            current_raw_ts = float(ts_arr[i])
            current_price = float(close_arr[i])
            current_backtest_ts = current_raw_ts / 1000.0
            
            exchange.set_current_index(i)

            # === [性能优化] 使用二分查找快速切片 ===
            idx_1h = bisect.bisect_right(ts_1h, current_raw_ts)
            idx_4h = bisect.bisect_right(ts_4h, current_raw_ts)
            idx_1d = bisect.bisect_right(ts_1d, current_raw_ts)
            
            slice_len = 200 
            slice_start = max(0, i - slice_len)
            
            base_closes_list = close_arr[slice_start:i+1]
            
            prices_dict = {
                'default': base_closes_list,
                '15m': base_closes_list,
                '1h': closes_1h[:idx_1h],
                '4h': closes_4h[:idx_4h],
                '1d': closes_1d[:idx_1d]
            }
            
            # 构造 data_map
            data_15m = []
            strategy_lookback = 100
            s_start = max(0, i - strategy_lookback)
            
            # 因为上面转成了 list，这里的 append 放入的都是原生 float/int，不会再报错
            for k in range(s_start, i+1):
                data_15m.append([
                    ts_arr[k], open_arr[k], high_arr[k], low_arr[k], close_arr[k], vol_arr[k]
                ])

            data_map = {
                '15m': data_15m,
                '1h': data_1h[:idx_1h],
                '4h': data_4h[:idx_4h],
                '1d': data_1d[:idx_1d]
            }
            
            # 策略特定数据准备
            extra_data = None
            if strategy_type == 'coffin':
                extra_data = {
                    'ohlcv_5m': data_15m, 
                    'ohlcv_15m': data_15m,
                    'current_time': current_backtest_ts 
                }

            fvgs = []
            if strategy_type == 'fvg' or (strategy_type == 'fib_grid' and cfg.get('use_fvg', False)):
                if i % 3 == 0: 
                    fvgs = await _update_fvgs_mock(strategy, exchange, symbol)
                    last_fvgs = fvgs
                else:
                    fvgs = last_fvgs

            # 策略分析
            if strategy_type == 'coffin':
                intent = strategy.analyze_market(state, current_price, extra_data=extra_data)
            else:
                intent = strategy.analyze_market(state, current_price, all_fvgs=fvgs)
            
            action = intent.get('action', 'none')
            pos_amt = float(state.get('position_amt', 0))
            
            # === 过滤逻辑 ===
            rsi_blocked = False

            if action == 'buy' and pos_amt == 0:
                intent_dir = state.get('direction', cfg.get('direction', 'long'))
                rsi_configs = cfg.get('rsi_conditions', [])
                
                long_configs = [c for c in rsi_configs if c.get('pos_side', 'long') == 'long']
                short_configs = [c for c in rsi_configs if c.get('pos_side') == 'short']
                
                if intent_dir == 'long' and long_configs:
                    rsi_pass, _ = check_rsi_conditions_mock(long_configs, prices_dict)
                    if not rsi_pass: rsi_blocked = True
                elif intent_dir == 'short' and short_configs:
                    rsi_pass, _ = check_rsi_conditions_mock(short_configs, prices_dict)
                    if not rsi_pass: rsi_blocked = True
                
                if rsi_blocked: action = 'none'

            # 高级过滤
            target_dir = state.get('direction', cfg.get('direction', 'long'))
            ma_configs = cfg.get('ma_conditions', [])
            active_ma_conds = [c for c in ma_configs if c.get('enabled', True) and c.get('pos_side', 'long') == target_dir]
            
            use_stoch = cfg.get('rsi_filter_stoch', False)
            use_bb    = cfg.get('rsi_filter_bb', False)
            use_adx   = cfg.get('rsi_filter_adx', False)
            use_vol   = cfg.get('rsi_filter_vol', False)
            use_ma_dynamic = len(active_ma_conds) > 0

            if action == 'buy' and pos_amt == 0 and not rsi_blocked and (use_stoch or use_bb or use_adx or use_vol or use_ma_dynamic):
                adv_pass = True
                
                if active_ma_conds:
                    for ma_c in active_ma_conds:
                        ma_tf = ma_c.get('tf', '15m')
                        ma_period = int(ma_c.get('period', 50))
                        ma_type = ma_c.get('ma_type', 'ema')
                        
                        ma_closes = prices_dict.get(ma_tf, [])
                        if ma_closes:
                            ma_val = calculate_ma(ma_closes, period=ma_period, ma_type=ma_type)
                            if ma_val > 0:
                                if target_dir == 'long' and current_price < ma_val: adv_pass = False
                                elif target_dir == 'short' and current_price > ma_val: adv_pass = False
                        else:
                            adv_pass = False

                if use_adx:
                    bars_4h = data_map.get('4h', [])
                    if bars_4h and len(bars_4h) > 20:
                        highs = [x[2] for x in bars_4h]
                        lows = [x[3] for x in bars_4h]
                        closes = [x[4] for x in bars_4h]
                        adx_val = calculate_adx(highs, lows, closes)
                        if adx_val >= 25: adv_pass = False

                volumes_slice = vol_arr[slice_start:i+1]
                if use_vol:
                    if volumes_slice:
                        is_spike, _, _ = check_volume_spike(volumes_slice, period=20, multiplier=1.5)
                        if not is_spike: adv_pass = False

                closes_15m = prices_dict.get('15m', [])
                if use_stoch and closes_15m:
                    stoch_k = calculate_stoch_rsi_k(closes_15m)
                    if target_dir == 'long' and stoch_k >= 20: adv_pass = False
                    elif target_dir == 'short' and stoch_k <= 80: adv_pass = False

                if use_bb and closes_15m:
                    bb_up, _, bb_low = calculate_bollinger_bands(closes_15m)
                    if target_dir == 'long' and current_price >= bb_low: adv_pass = False
                    elif target_dir == 'short' and current_price <= bb_up: adv_pass = False

                if not adv_pass: action = 'none'

            # === 执行 ===
            if intent.get('update_msg'):
                if 'range_top' in intent: state['range_top'] = intent['range_top']
                if 'range_bottom' in intent: state['range_bottom'] = intent['range_bottom']
            
            if action == 'update_trail':
                state['is_trailing_active'] = True
                dir_ = cfg.get('direction', 'long')
                if dir_ == 'short':
                    old_l = float(state.get('lowest_price_seen', 0))
                    if old_l == 0 or current_price < old_l: state['lowest_price_seen'] = current_price
                else:
                    old_h = float(state.get('highest_price_seen', 0))
                    if old_h == 0 or current_price > old_h: state['highest_price_seen'] = current_price
            
            elif action == 'buy':
                cost = intent.get('cost', 0)
                fee_rate = float(cfg.get('fee_rate', 0.0005))
                leverage = float(cfg.get('leverage', 1.0))
                amount_precision = float(cfg.get('amount_precision', 0.001))
                
                notional = cost * leverage
                raw_amount = notional / current_price
                
                raw_amt_d = Decimal(str(raw_amount))
                precision_d = Decimal(str(amount_precision))
                amt_d = (raw_amt_d / precision_d).to_integral_value(rounding=ROUND_DOWN) * precision_d
                amount = float(amt_d)
                
                actual_value = amount * current_price
                min_notional = 5.0
                
                balance = float(state.get('balance', 0))
                fee = actual_value * fee_rate
                required = (actual_value / leverage) + fee
                
                if amount > 0 and actual_value >= min_notional and balance >= required:
                    state['balance'] = balance - (actual_value / leverage) - fee
                    
                    old_amt = float(state.get('position_amt', 0))
                    old_total_cost = float(state.get('total_cost', 0)) 
                    old_avg = float(state.get('avg_price', 0))
                    
                    if old_amt == 0:
                        new_avg = current_price
                    else:
                        old_notional = old_amt * old_avg
                        new_notional = amount * current_price
                        new_avg = (old_notional + new_notional) / (old_amt + amount)
                    
                    state['position_amt'] = old_amt + amount
                    state['total_cost'] = old_total_cost + (actual_value / leverage)
                    state['avg_price'] = new_avg
                    
                    if 'orders' not in state: state['orders'] = []
                    state['orders'].append({
                        'level_idx': intent.get('new_level_idx', -1),
                        'price': current_price,
                        'amount': amount,
                        'cost': float(actual_value / leverage),
                        'time': current_backtest_ts
                    })
                    
                    if strategy_type == 'fvg':
                        if intent.get('is_base'):
                            state['initial_base_price'] = current_price
                            state['current_so_index'] = 2
                            state['highest_price_seen'] = current_price
                            state['lowest_price_seen'] = current_price
                        else:
                            c_idx = state.get('current_so_index', 1)
                            state['current_so_index'] = c_idx + 1

                    if 'new_level_idx' in intent:
                        state['last_level_idx'] = intent['new_level_idx']
                        
                    await db.add_log(bot_id, intent.get('log_action', "Buy"), current_price, amount, 0, fee, intent.get('log_note', ''))

            elif action == 'sell':
                pos_amt = float(state.get('position_amt', 0))
                if pos_amt > 0:
                    avg_price = float(state.get('avg_price', 0))
                    total_margin = float(state.get('total_cost', 0))
                    fee_rate = float(cfg.get('fee_rate', 0.0005))
                    direction = state.get('direction', cfg.get('direction', 'long'))
                    
                    close_notional = pos_amt * current_price
                    close_fee = close_notional * fee_rate
                    
                    if direction == 'short':
                        pnl = (avg_price - current_price) * pos_amt
                    else:
                        pnl = (current_price - avg_price) * pos_amt
                        
                    balance_return = total_margin + pnl - close_fee
                    state['balance'] = float(state.get('balance', 0)) + balance_return
                    
                    realized_profit = pnl - close_fee
                    state['current_profit'] = float(state.get('current_profit', 0)) + realized_profit
                    
                    await db.add_log(bot_id, intent.get('log_action', "Sell"), current_price, pos_amt, realized_profit, close_fee, intent.get('log_note', ''))
                    
                    state['position_amt'] = 0
                    state['avg_price'] = 0
                    state['total_cost'] = 0
                    state['orders'] = []
                    state['last_close_time'] = current_backtest_ts 
                    state['is_trailing_active'] = False
                    state['highest_price_seen'] = 0.0
                    state['lowest_price_seen'] = 0.0

                    if strategy_type == 'fvg':
                        state['current_so_index'] = 1
                    
                    if intent.get('reset_coffin'):
                        state['stage'] = 'IDLE'
                        state['stop_loss_price'] = 0.0
                        state['extreme_price'] = 0.0
                        state['breakout_dir'] = None
                        
                    if intent.get('reset_range'):
                        state['range_top'] = 0.0
                        state['range_bottom'] = 0.0
                        state['last_level_idx'] = -1

        await db.update_bot_state(bot_id, state, t("backtest_completed"))
        print(f"✅ Bot {bot_id} Backtest Finished. Final Balance: {state['balance']:.2f}")
        return True, "Success"

    except Exception as e:
        traceback.print_exc()
        return False, str(e)