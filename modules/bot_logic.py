import time
import asyncio
import pandas as pd
import traceback
import numpy as np
from decimal import Decimal, ROUND_DOWN
from modules.database import db
from modules.strategies import get_strategy_class
from languages import TRANSLATIONS
from modules.globals import RUNTIME_CACHE, WS_PRICE_CACHE, get_bot_lock
from modules.exchange_manager import get_cached_exchange

from modules.indicators import (
    calculate_ma, calculate_rsi_value, calculate_bollinger_bands,
    calculate_stoch_rsi_k, calculate_adx, check_volume_spike
)

# ================= 辅助指标 =================
async def check_rsi_conditions(rsi_configs, exchange, symbol):
    if not rsi_configs: return True, ""
    active_conds = [c for c in rsi_configs if c.get('enabled')]
    if not active_conds: return True, ""
    
    tfs = set(c['tf'] for c in active_conds)
    tf_list = list(tfs)
    
    data_map = {}
    tasks = []
    fetch_needed_indices = []

    # 1. 检查缓存
    now_ts = time.time()
    for i, tf in enumerate(tf_list):
        cache_key = f"rsi_data_{symbol}_{tf}"
        cached = RUNTIME_CACHE.get(cache_key)
        
        # 缓存有效期设为 50 秒 (略小于K线周期)
        if cached and (now_ts - cached['ts'] < 50):
            data_map[tf] = cached['data']
        else:
            tasks.append(exchange.fetch_ohlcv(symbol, timeframe=tf, limit=50))
            fetch_needed_indices.append(i)
    
    # 2. 仅请求未命中的数据
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for idx, res in enumerate(results):
            original_idx = fetch_needed_indices[idx]
            tf = tf_list[original_idx]
            
            if isinstance(res, list) and len(res) > 0:
                data_map[tf] = res
                # 写入缓存
                RUNTIME_CACHE[f"rsi_data_{symbol}_{tf}"] = {'ts': now_ts, 'data': res}
            else:
                return False, f"RSI Fetch Error: {tf}"
            
    status_details = []
    all_passed = True
    for c in active_conds:
        tf = c['tf']
        try:
            threshold = float(c['val'])
        except: continue
        bars = data_map.get(tf)
        if not bars or len(bars) < 15: return False, f"RSI Data Insufficient"
        
        closes = [x[4] for x in bars]
        rsi_val = calculate_rsi_value(closes)
        op = c['op']
        passed = (rsi_val < threshold) if op == '<' else (rsi_val > threshold)
        
        icon = "✅" if passed else "❌"
        status_details.append(f"{tf}({rsi_val:.1f}{op}{int(threshold)}){icon}")
        if not passed: all_passed = False
            
    return all_passed, " ".join(status_details)

async def _update_fvgs_cache(bot_id, cfg, exchange, brain, symbol):
    # 1. 频率控制 (每 60 秒更新一次，避免请求过于频繁)
    last_update = RUNTIME_CACHE[bot_id].get('last_fvg_update_time', 0)
    if time.time() - last_update < 60:
        return

    # 2. 定义要扫描的周期 (通常关注 1h 和 4h 的 FVG)
    timeframes = ['1h', '4h'] 
    
    tasks = []
    for tf in timeframes:
        # 调用策略内部的 find_fvgs 方法
        tasks.append(brain.find_fvgs(exchange, symbol, tf))
    
    # 3. 并发执行获取
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_fvgs = []
    for res in results:
        if isinstance(res, list):
            all_fvgs.extend(res)
            
    # 4. 更新缓存
    RUNTIME_CACHE[bot_id]['fvgs'] = all_fvgs
    RUNTIME_CACHE[bot_id]['last_fvg_update_time'] = time.time()

# ================= 核心逻辑 =================

async def run_bot_logic(bot_data):
    bot_id = bot_data['id']
    cfg = bot_data['config']
    snapshot_state = bot_data['state']

    user_exchange_source = bot_data.get('exchange_source', 'binance')
    cfg = bot_data['config']
    cfg['user_id'] = bot_data.get('user_id')
    cfg['api_key'] = bot_data.get('api_key')
    cfg['api_secret'] = bot_data.get('api_secret')
    cfg['exchange_source'] = bot_data.get('exchange_source', 'binance')
    
    # === [新增] 1. 多语言支持准备 ===
    user_lang = bot_data.get('language', 'zh-CN')
    
    def t(key):
        lang_dict = TRANSLATIONS.get(user_lang, TRANSLATIONS['zh-CN'])
        return lang_dict.get(key, key)

    symbol = bot_data.get('symbol') or cfg.get('symbol')
    if not symbol:
        print(f"⚠️ Bot {bot_id} Missing Symbol")
        return
    
    strat_type = bot_data.get('strategy_type', 'fvg')
    
    leverage = float(cfg.get('leverage', 1.0))
    if leverage < 1: leverage = 1.0

    if bot_id not in RUNTIME_CACHE:
        RUNTIME_CACHE[bot_id] = {
            'market_price': 0.0, 
            'ladder': [], 
            'fvgs': [], 
            'last_fvg_update_time': 0, 
            'last_db_write': 0,
            'last_pos_sync': 0
        }
    
    try:
        exchange = get_cached_exchange(cfg)
    except Exception as e:
        print(f"Exchange init error: {e}")
        return

    # ============================================================
    # 1. 获取行情
    # ============================================================
    try:
        StrategyClass = get_strategy_class(strat_type)
        brain = StrategyClass(cfg, t_func=t, now_func=time.time)
        
        current_price = 0.0
        is_ws_allowed = (cfg.get('market_type', 'future') == 'future')
        
        if user_exchange_source == 'pionex':
            is_ws_allowed = False 

        if is_ws_allowed:
            ws_data = WS_PRICE_CACHE.get(symbol)
            if ws_data and (time.time() - ws_data['ts'] < 10):
                current_price = ws_data['price']
        
        if current_price <= 0:
            ticker = await exchange.fetch_ticker(symbol)
            current_price = float(ticker['last'])

        if current_price <= 0: return 

        RUNTIME_CACHE[bot_id]['market_price'] = current_price

        # ============================================================
        # [修改] 2.5 RSI 条件过滤 (分别计算多/空 RSI 状态)
        # ============================================================
        rsi_pass_long = True
        rsi_msg_long = ""
        rsi_pass_short = True
        rsi_msg_short = ""
        
        pos_amt = float(snapshot_state.get('position_amt', 0))
        rsi_configs = cfg.get('rsi_conditions', [])

        if pos_amt == 0 and rsi_configs:
            try:
                # 拆分多空配置
                # 兼容旧配置：如果没有 pos_side 字段，默认为 'long'
                long_configs = [c for c in rsi_configs if c.get('pos_side', 'long') == 'long']
                short_configs = [c for c in rsi_configs if c.get('pos_side') == 'short']
                
                # 分别检查
                if long_configs:
                    rsi_pass_long, rsi_msg_long = await check_rsi_conditions(long_configs, exchange, symbol)
                
                if short_configs:
                    rsi_pass_short, rsi_msg_short = await check_rsi_conditions(short_configs, exchange, symbol)
                    
            except Exception as e:
                print(f"RSI Check Error: {e}")
                rsi_pass_long = False
                rsi_pass_short = False

        # ============================================================
        # 2. 策略前置数据准备 (K线/FVG)
        # ============================================================
        extra_data = {}
        all_fvgs = []
        ladder = []

        if strat_type == 'coffin':
            try:
                task_5m = exchange.fetch_ohlcv(symbol, '5m', limit=100)
                task_15m = exchange.fetch_ohlcv(symbol, '15m', limit=100)
                res = await asyncio.gather(task_5m, task_15m, return_exceptions=True)
                
                extra_data = {
                    'ohlcv_5m': res[0] if isinstance(res[0], list) else [],
                    'ohlcv_15m': res[1] if isinstance(res[1], list) else []
                }
            except Exception as e:
                pass 

        elif strat_type == 'fvg' or (strat_type == 'fib_grid' and cfg.get('use_fvg', False)):
            await _update_fvgs_cache(bot_id, cfg, exchange, brain, symbol)
            all_fvgs = RUNTIME_CACHE[bot_id].get('fvgs', [])
        
        # ============================================================
        # 3. 生成梯子预览
        # ============================================================
        if strat_type not in ['coffin']:
            anchor = float(snapshot_state.get('initial_base_price', 0))
            if strat_type == 'grid_dca': 
                anchor = float(snapshot_state.get('range_top', 0))
            elif strat_type == 'fib_grid': 
                anchor = float(snapshot_state.get('range_top', 0)) or float(cfg.get('range_top', 0))

            if anchor <= 0: anchor = current_price
            
            so_idx = int(snapshot_state.get('current_so_index', 1))
            if strat_type in ['fib_grid', 'grid_dca']: 
                so_idx = int(snapshot_state.get('last_level_idx', -1))

            try:
                ladder = brain.generate_ladder(anchor, so_idx, current_price)
            except Exception:
                ladder = []
        
        RUNTIME_CACHE[bot_id]['ladder'] = ladder

        if not bot_data.get('is_running'):
            return

        # ============================================================
        # 4. 策略分析
        # ============================================================
        if strat_type == 'coffin':
            intent = brain.analyze_market(snapshot_state, current_price, extra_data=extra_data)
        else:
            intent = brain.analyze_market(snapshot_state, current_price, all_fvgs)
        
        has_position = float(snapshot_state.get('position_amt', 0)) != 0
        
        force_status_update = False
        current_msg = bot_data.get('status_msg', '')
        
        starting_keywords = [
            TRANSLATIONS.get(lang, {}).get('status_starting', 'Starting')
            for lang in TRANSLATIONS.keys()
        ]
        
        for kw in starting_keywords:
            if kw in current_msg:
                force_status_update = True
                break

        if intent['action'] == 'none' and not intent.get('update_msg') and not intent.get('new_level_idx') and not force_status_update and not has_position:
            current_status = intent.get('status_msg', bot_data['status_msg'])
            last_status = bot_data['status_msg']
            if current_status == last_status:
                return 
            
            now = time.time()
            last_write = RUNTIME_CACHE[bot_id].get('last_db_write', 0)
            if now - last_write < 3: return 

        # ============================================================
        # 5. 执行意图 & 状态更新
        # ============================================================
        lock = get_bot_lock(bot_id)
        async with lock:
            latest_bot = await db.get_bot_full_data(bot_id)
            if not latest_bot or not latest_bot['is_running']: return 
            
            fresh_state = latest_bot['state']
            save_needed = False
            
            current_pnl = 0
            direction = fresh_state.get('direction', cfg.get('direction', 'long'))
            pos_amt = float(fresh_state.get('position_amt', 0))
            avg_price = float(fresh_state.get('avg_price', 0))

            if pos_amt != 0:
                if direction == 'short':
                    current_pnl = (avg_price - current_price) * pos_amt
                else:
                    current_pnl = (current_price - avg_price) * pos_amt
            
            profit_arg = float(latest_bot.get('current_profit', 0)) 

            status_msg = intent.get('status_msg', latest_bot['status_msg'])
            
            current_db_status = latest_bot.get('status_msg', '')
            is_starting_status = False
            for kw in starting_keywords:
                if kw in current_db_status:
                    is_starting_status = True
                    break
            
            if is_starting_status:
                status_msg = t("status_running") 
                save_needed = True
            
            if 'new_level_idx' in intent:
                fresh_state['last_level_idx'] = intent['new_level_idx']
                save_needed = True
            
            if intent.get('reset_coffin'):
                 fresh_state['stage'] = 'IDLE'
                 fresh_state['stop_loss_price'] = 0.0
                 fresh_state['extreme_price'] = 0.0
                 save_needed = True

            if strat_type == 'coffin' and intent.get('update_msg'):
                if 'coffin_5m' in snapshot_state: fresh_state['coffin_5m'] = snapshot_state['coffin_5m']
                if 'coffin_15m' in snapshot_state: fresh_state['coffin_15m'] = snapshot_state['coffin_15m']

                if 'last_traded_coffin_id' in snapshot_state: 
                    fresh_state['last_traded_coffin_id'] = snapshot_state['last_traded_coffin_id']
                
                current_pos = float(fresh_state.get('position_amt', 0))
                if abs(current_pos) == 0 or snapshot_state.get('stage') == 'IN_POS':
                    if 'stage' in snapshot_state: fresh_state['stage'] = snapshot_state['stage']
                    if 'breakout_dir' in snapshot_state: fresh_state['breakout_dir'] = snapshot_state['breakout_dir']

                if 'breakout_price' in snapshot_state: fresh_state['breakout_price'] = snapshot_state['breakout_price']
                
                new_sl = float(snapshot_state.get('stop_loss_price', 0))
                if new_sl > 0: fresh_state['stop_loss_price'] = new_sl
                    
                new_extreme = float(snapshot_state.get('extreme_price', 0))
                if new_extreme > 0: fresh_state['extreme_price'] = new_extreme
                save_needed = True

            if intent.get('update_msg') and strat_type != 'coffin':
                if 'range_top' in snapshot_state: fresh_state['range_top'] = snapshot_state['range_top']
                if 'range_bottom' in snapshot_state: fresh_state['range_bottom'] = snapshot_state['range_bottom']
                if 'last_invest_time' in snapshot_state: fresh_state['last_invest_time'] = snapshot_state['last_invest_time']
                save_needed = True

            action = intent['action']

            rsi_blocked = False # 初始化变量，防止报错

            if action == 'buy' and pos_amt == 0:
                # 判定当前意图的方向
                intent_dir = fresh_state.get('direction', cfg.get('direction', 'long'))
                
                # 最终检查
                block_msg = ""
                
                if intent_dir == 'long':
                    if not rsi_pass_long:
                        rsi_blocked = True
                        block_msg = f"⏳ RSI(L) Wait: {rsi_msg_long}"
                elif intent_dir == 'short':
                    if not rsi_pass_short:
                        rsi_blocked = True
                        block_msg = f"⏳ RSI(S) Wait: {rsi_msg_short}"
                
                if rsi_blocked:
                    action = 'none' 
                    status_msg = block_msg 
                    save_needed = True
                    if latest_bot['status_msg'] == status_msg:
                        save_needed = False

            # ================= 后执行新的硬性过滤逻辑 =================

            target_dir = fresh_state.get('direction', cfg.get('direction', 'long'))

            ma_configs = cfg.get('ma_conditions', [])
            active_ma_conds = []
            if ma_configs:
                # 筛选出：启用状态 (enabled=True) 且 方向匹配 (pos_side == target_dir) 的条件
                active_ma_conds = [
                    c for c in ma_configs 
                    if c.get('enabled', True) and c.get('pos_side', 'long') == target_dir
                ]

            use_stoch = cfg.get('rsi_filter_stoch', False)
            use_bb    = cfg.get('rsi_filter_bb', False)
            use_adx   = cfg.get('rsi_filter_adx', False)
            use_vol   = cfg.get('rsi_filter_vol', False)
            
            # 是否有任何 MA 条件需要检查
            use_ma_dynamic = len(active_ma_conds) > 0

            if action == 'buy' and pos_amt == 0 and not rsi_blocked and (use_stoch or use_bb or use_adx or use_vol or use_ma_dynamic):
                adv_pass = True
                adv_msg_list = []
                
                # A. 准备数据
                req_tfs = set()
                if use_stoch or use_bb: req_tfs.add('15m')
                if use_adx: req_tfs.add('4h')

                for c in active_ma_conds:
                    req_tfs.add(c.get('tf', '15m'))
                
                data_map = {}
                tasks = []
                fetch_indices = []
                req_tfs_list = list(req_tfs)
                now_ts = time.time()
                
                for i, tf in enumerate(req_tfs_list):
                    cache_key = f"adv_filter_{symbol}_{tf}"
                    cached = RUNTIME_CACHE.get(cache_key)
                    if cached and (now_ts - cached['ts'] < 55):
                        data_map[tf] = cached['data']
                    else:
                        tasks.append(exchange.fetch_ohlcv(symbol, timeframe=tf, limit=200))
                        fetch_indices.append(i)
                
                if tasks:
                    res_list = await asyncio.gather(*tasks, return_exceptions=True)
                    for idx, res in enumerate(res_list):
                        tf = req_tfs_list[fetch_indices[idx]]
                        if isinstance(res, list) and len(res) > 20:
                            data_map[tf] = res
                            RUNTIME_CACHE[f"adv_filter_{symbol}_{tf}"] = {'ts': now_ts, 'data': res}

                #MA 趋势过滤核心逻辑
                if active_ma_conds:
                    for ma_c in active_ma_conds:
                        ma_tf = ma_c.get('tf', '15m')
                        ma_period = int(ma_c.get('period', 50))
                        ma_type = ma_c.get('ma_type', 'ema')
                        
                        if ma_tf in data_map:
                            k_ma = data_map[ma_tf]
                            closes_ma = [x[4] for x in k_ma]
                            ma_val = calculate_ma(closes_ma, period=ma_period, ma_type=ma_type)
                            
                            if ma_val > 0:
                                # 顺势逻辑：做多要求价格 > MA，做空要求价格 < MA
                                if target_dir == 'long' and current_price < ma_val:
                                    adv_pass = False
                                    adv_msg_list.append(t('filter_wait_ma').format(p=current_price, m=ma_val) + f"({ma_tf} {ma_type.upper()}{ma_period})")
                                elif target_dir == 'short' and current_price > ma_val:
                                    adv_pass = False
                                    adv_msg_list.append(t('filter_wait_ma').format(p=current_price, m=ma_val) + f"({ma_tf} {ma_type.upper()}{ma_period})")
                        else:
                            # 缺数据时默认拦截
                            adv_pass = False
                            adv_msg_list.append(f"MA {ma_tf} Data N/A")
                
                # B. 执行过滤判断
                target_dir = fresh_state.get('direction', cfg.get('direction', 'long'))
                
                # 1. ADX (4H)
                if use_adx:
                    if '4h' in data_map:
                        k = data_map['4h']
                        adx = calculate_adx([x[2] for x in k], [x[3] for x in k], [x[4] for x in k])
                        if adx >= 25:
                            adv_pass = False
                            adv_msg_list.append(t('filter_wait_adx').format(adx=adx))
                    else:
                        adv_pass = False
                        adv_msg_list.append("ADX Data N/A")

                # 准备 15m 数据
                k15 = data_map.get('15m', [])
                closes_15m = [x[4] for x in k15] if k15 else []
                volumes_15m = [x[5] for x in k15] if k15 else []

                # [新增] 2. Volume Spike (15m)
                if use_vol:
                    if volumes_15m:
                        is_spike, cur_v, target_v = check_volume_spike(volumes_15m, period=20, multiplier=1.5)
                        if not is_spike:
                            adv_pass = False
                            adv_msg_list.append(t('filter_wait_vol').format(v=cur_v, t=target_v))
                    else:
                        adv_pass = False
                        adv_msg_list.append("Vol Data N/A")
                
                # 3. StochRSI (15m)
                if use_stoch:
                    if closes_15m:
                        stoch_k = calculate_stoch_rsi_k(closes_15m)
                        if target_dir == 'long' and stoch_k >= 20:
                            adv_pass = False
                            adv_msg_list.append(t('filter_wait_stoch').format(k=stoch_k))
                        elif target_dir == 'short' and stoch_k <= 80:
                            adv_pass = False
                            adv_msg_list.append(t('filter_wait_stoch').format(k=stoch_k))
                    else:
                        adv_pass = False
                        adv_msg_list.append("Stoch Data N/A")

                # 4. Bollinger Bands (15m)
                if use_bb:
                    if closes_15m:
                        bb_up, bb_mid, bb_low = calculate_bollinger_bands(closes_15m)
                        if target_dir == 'long' and current_price >= bb_low:
                            adv_pass = False
                            adv_msg_list.append(t('filter_wait_bb').format(p=current_price, b=bb_low))
                        elif target_dir == 'short' and current_price <= bb_up:
                            adv_pass = False
                            adv_msg_list.append(t('filter_wait_bb').format(p=current_price, b=bb_up))
                    else:
                        adv_pass = False
                        adv_msg_list.append("BB Data N/A")

                # C. 拦截动作
                if not adv_pass:
                    action = 'none'
                    status_msg = t('filter_wait_msg').format(details=" ".join(adv_msg_list))
                    save_needed = True
                    if latest_bot['status_msg'] == status_msg:
                        save_needed = False

            fee_rate = float(cfg.get('fee_rate', 0.0005))
            amount_precision = float(cfg.get('amount_precision', 0.001))

            if action == 'update_trail':
                fresh_state['is_trailing_active'] = True
                if direction == 'short':
                    old_low = float(fresh_state.get('lowest_price_seen', 0))
                    if old_low <= 0: old_low = current_price
                    fresh_state['lowest_price_seen'] = min(old_low, current_price)
                else:
                    old_high = float(fresh_state.get('highest_price_seen', 0))
                    if old_high == 0: old_high = current_price
                    fresh_state['highest_price_seen'] = max(old_high, current_price)
                
                if intent.get('log_note'):
                    await db.add_log(bot_id, t("log_trailing_active"), current_price, 0, 0, 0, intent['log_note'])
                save_needed = True

            elif action == 'buy':
                cost_budget = intent['cost']
                cost_budget_d = Decimal(str(cost_budget))
                current_price_d = Decimal(str(current_price))
                fee_rate_d = Decimal(str(fee_rate))
                leverage_d = Decimal(str(leverage))
                balance_d = Decimal(str(fresh_state.get('balance', 0)))
                
                required_total_d = cost_budget_d * (1 + leverage_d * fee_rate_d)

                if balance_d < required_total_d:
                    adjusted_budget_d = balance_d / (1 + leverage_d * fee_rate_d) * Decimal("0.999")
                    if adjusted_budget_d > cost_budget_d * Decimal("0.1"): 
                        cost_budget_d = adjusted_budget_d
                        notional_value_d = cost_budget_d * leverage_d
                        fee_val_d = notional_value_d * fee_rate_d
                        required_balance = cost_budget_d + fee_val_d
                    else:
                        notional_value_d = cost_budget_d * leverage_d
                        fee_val_d = notional_value_d * fee_rate_d
                        required_balance = required_total_d
                else:
                    notional_value_d = cost_budget_d * leverage_d
                    fee_val_d = notional_value_d * fee_rate_d
                    required_balance = cost_budget_d + fee_val_d

                if balance_d >= required_balance: 
                    raw_amt_d = notional_value_d / current_price_d
                    precision_d = Decimal(str(amount_precision))
                    amt_d = (raw_amt_d / precision_d).to_integral_value(rounding=ROUND_DOWN) * precision_d
                    amt = float(amt_d) 
                    
                    if amt <= 0:
                        await db.add_log(bot_id, t("error"), current_price, 0, 0, 0, f"{t('err_qty_too_small')}: {raw_amt_d}")
                        return

                    actual_notional_d = amt_d * current_price_d
                    actual_margin_d = actual_notional_d / leverage_d
                    actual_fee_d = actual_notional_d * fee_rate_d
                    
                    pos_amt_d = Decimal(str(fresh_state.get('position_amt', 0)))
                    avg_price_d = Decimal(str(fresh_state.get('avg_price', 0)))
                    total_margin_d = Decimal(str(fresh_state.get('total_cost', 0)))

                    if pos_amt_d == 0:
                        new_avg_price_d = current_price_d
                        if strat_type == 'coffin' and 'direction' in snapshot_state:
                            fresh_state['direction'] = snapshot_state['direction']
                    else:
                        old_notional = pos_amt_d * avg_price_d
                        new_notional = amt_d * current_price_d
                        new_avg_price_d = (old_notional + new_notional) / (pos_amt_d + amt_d)

                    fresh_state['position_amt'] = float(pos_amt_d + amt_d)
                    fresh_state['balance'] = float(balance_d - actual_margin_d - actual_fee_d)
                    fresh_state['total_cost'] = float(total_margin_d + actual_margin_d) 
                    fresh_state['avg_price'] = float(new_avg_price_d)

                    if 'orders' not in fresh_state: fresh_state['orders'] = []
                    fresh_state['orders'].append({
                        'level_idx': intent.get('new_level_idx', -1),
                        'price': current_price,
                        'amount': amt,
                        'cost': float(actual_margin_d),
                        'time': time.time()
                    })

                    if strat_type == 'fvg':
                        if intent.get('is_base'):
                            fresh_state['initial_base_price'] = current_price
                            fresh_state['current_so_index'] = 2
                            fresh_state['highest_price_seen'] = current_price
                            fresh_state['lowest_price_seen'] = current_price
                        else:
                            fresh_state['current_so_index'] += 1

                    await db.add_log(bot_id, intent.get('log_action', t('log_buy')), current_price, amt, 0, float(actual_fee_d), intent['log_note'])
                    save_needed = True
                else:
                    status_msg = f"{t('status_insufficient_balance')} (Need {required_balance:.2f})"
                    save_needed = True

            elif action == 'sell':
                pos_amt = fresh_state['position_amt']
                if pos_amt != 0:
                    pos_amt_d = Decimal(str(pos_amt))
                    avg_price_d = Decimal(str(fresh_state['avg_price']))
                    total_margin_d = Decimal(str(fresh_state['total_cost']))
                    
                    current_price_d = Decimal(str(current_price))
                    fee_rate_d = Decimal(str(fee_rate))
                    
                    close_notional_d = pos_amt_d * current_price_d
                    close_fee_d = close_notional_d * fee_rate_d
                    
                    pnl_d = Decimal(0)
                    if direction == 'short':
                        pnl_d = (avg_price_d - current_price_d) * pos_amt_d
                    else:
                        pnl_d = (current_price_d - avg_price_d) * pos_amt_d
                    
                    balance_return_d = total_margin_d + pnl_d - close_fee_d
                    fresh_state['balance'] = float(Decimal(str(fresh_state['balance'])) + balance_return_d)
                    
                    realized_profit = float(pnl_d - close_fee_d) 
                    
                    await db.add_log(bot_id, intent.get('log_action', t('log_sell')), current_price, pos_amt, realized_profit, float(close_fee_d), intent['log_note'])
                    
                    profit_arg += realized_profit

                    fresh_state['position_amt'] = 0
                    fresh_state['avg_price'] = 0
                    fresh_state['total_cost'] = 0
                    fresh_state['orders'] = []
                    fresh_state['last_close_time'] = time.time()
                    
                    fresh_state['is_trailing_active'] = False
                    fresh_state['highest_price_seen'] = 0.0
                    fresh_state['lowest_price_seen'] = 0.0

                    if strat_type == 'fvg':
                        fresh_state['current_so_index'] = 1
                        
                    if intent.get('reset_range'):
                        fresh_state['range_top'] = 0.0
                        fresh_state['range_bottom'] = 0.0
                        fresh_state['last_level_idx'] = -1
                        
                    save_needed = True

            current_check = await db.get_bot_full_data(bot_id)
            if not current_check or not current_check['is_running']:
                return 

            if save_needed or has_position:
                await db.update_bot_state(bot_id, fresh_state, status_msg, profit_arg)
                RUNTIME_CACHE[bot_id]['last_db_write'] = time.time()
            elif status_msg != latest_bot['status_msg']:
                now = time.time()
                last_write = RUNTIME_CACHE[bot_id].get('last_db_write', 0)
                if now - last_write > 3:
                    await db.update_bot_state(bot_id, fresh_state, status_msg, profit_arg)
                    RUNTIME_CACHE[bot_id]['last_db_write'] = now

    except Exception as e:
        err_str = str(e)
        
        # [新增] 如果是保存设置导致的连接断开，直接忽略，不报错
        if "Session is closed" in err_str or "connector" in err_str or isinstance(e, AssertionError):
             return

        # 其他错误照常显示
        if "Network Error" not in err_str:
             print(f"Bot {bot_id} Error: {e}")
             traceback.print_exc()