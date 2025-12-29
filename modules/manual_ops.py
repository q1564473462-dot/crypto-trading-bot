import time
from decimal import Decimal, ROUND_DOWN
from modules.database import db
from modules.globals import RUNTIME_CACHE, get_bot_lock
from modules.exchange_manager import get_cached_exchange
from languages import TRANSLATIONS

async def execute_manual_buy(bot_id, amount_usd):
    lock = get_bot_lock(bot_id)
    async with lock:
        bot_data = await db.get_bot_full_data(bot_id)
        if not bot_data: raise Exception("Bot not found")

        user_lang = bot_data.get('language', 'zh-CN')
        def t(key):
            return TRANSLATIONS.get(user_lang, TRANSLATIONS['zh-CN']).get(key, key)
        # ===========================
        
        state = bot_data['state']
        cfg = bot_data['config']

        cfg['user_id'] = bot_data.get('user_id')
        cfg['api_key'] = bot_data.get('api_key')
        cfg['api_secret'] = bot_data.get('api_secret')
        cfg['exchange_source'] = bot_data.get('exchange_source', 'binance')

        fee_rate = float(cfg.get('fee_rate', 0.0005))
        precision = float(cfg.get('amount_precision', 0.001))
        leverage = float(cfg.get('leverage', 1.0))
        if cfg.get('market_type') == 'spot':
            leverage = 1.0
        strategy_type = bot_data.get('strategy_type', 'fvg') # 获取策略类型
        
        # --- [修复] 1. 增强型价格获取逻辑 ---
        price = RUNTIME_CACHE.get(bot_id, {}).get('market_price', 0)
        
        # 如果缓存没数据（比如刚启动），现场去交易所查一次
        if price <= 0:
            try:
                exchange = get_cached_exchange(cfg)
                symbol = bot_data.get('symbol') or cfg.get('symbol')
                ticker = await exchange.fetch_ticker(symbol)
                price = float(ticker['last'])
                
                # 顺便写入缓存
                if bot_id not in RUNTIME_CACHE: RUNTIME_CACHE[bot_id] = {}
                RUNTIME_CACHE[bot_id]['market_price'] = price
                print(f">>> [手动补救] 现场获取到价格: {price}")
            except Exception as e:
                print(f"Manual buy fetch price error: {e}")

        if price <= 0: raise Exception(t("err_price_fetch_retry"))
        
        # --- 2. 资金计算 ---
        amt_usd_d = Decimal(str(amount_usd)) 
        price_d = Decimal(str(price))
        fee_rate_d = Decimal(str(fee_rate))
        leverage_d = Decimal(str(leverage))
        bal_d = Decimal(str(state.get('balance', 0)))

        required_d = amt_usd_d * (1 + leverage_d * fee_rate_d)

        # 余额不足时的自动降级尝试
        if bal_d < required_d:
            adjusted_amt = bal_d / (1 + leverage_d * fee_rate_d) * Decimal("0.999") 
            if adjusted_amt > amt_usd_d * Decimal("0.1"):
                amt_usd_d = adjusted_amt
            else:
                raise Exception(f"{t('status_insufficient_balance')} ({t('need')} {required_d:.2f}, {t('have')} {bal_d:.2f})")

        notional_d = amt_usd_d * leverage_d
        raw_amt_d = notional_d / price_d
        
        # 精度截断
        precision_d = Decimal(str(precision))
        amt_d = (raw_amt_d / precision_d).to_integral_value(rounding=ROUND_DOWN) * precision_d
        
        if amt_d <= 0: raise Exception(t("err_order_amount_too_small"))

        # 实际消耗计算
        actual_notional_d = amt_d * price_d
        actual_margin_d = actual_notional_d / leverage_d
        actual_fee_d = actual_notional_d * fee_rate_d

        # --- 3. 更新资金与持仓 ---
        state['balance'] = float(bal_d - actual_margin_d - actual_fee_d)
        
        pos_amt_d = Decimal(str(state.get('position_amt', 0)))
        avg_price_d = Decimal(str(state.get('avg_price', 0)))
        
        if pos_amt_d == 0:
            state['avg_price'] = float(price)
            # 如果是首单，确保方向正确
            state['direction'] = cfg.get('direction', 'long') 
        else:
            # 计算加权均价
            old_val = pos_amt_d * avg_price_d
            new_val = amt_d * price_d
            state['avg_price'] = float((old_val + new_val) / (pos_amt_d + amt_d))
            
        state['position_amt'] = float(pos_amt_d + amt_d)
        state['total_cost'] = float(Decimal(str(state.get('total_cost', 0))) + actual_margin_d)

        # --- 4. [核心] 策略状态自动对齐 (防止卡死) ---
        
        # A. 针对 FVG / 趋势马丁
        if strategy_type == 'fvg':
            # [优化] 根据持仓金额智能推算当前应该在第几单
            base_order = float(cfg.get('capital', 1000))
            total_cost = float(state.get('total_cost', 0))
            total_capital = float(cfg.get('capital', 1000))
            
            # 估算当前仓位占比
            usage_ratio = total_cost / total_capital
            
            estimated_so = 1
            if usage_ratio > 0.05: estimated_so = 2
            if usage_ratio > 0.15: estimated_so = 3
            if usage_ratio > 0.30: estimated_so = 4
            if usage_ratio > 0.50: estimated_so = 5
            if usage_ratio > 0.75: estimated_so = 6
            
            # 取由于手动加仓单纯+1 和 智能估算 的较大值
            current_so = int(state.get('current_so_index', 1))
            state['current_so_index'] = max(current_so + 1, estimated_so)
            
            state['is_trailing_active'] = False 
            state['highest_price_seen'] = 0.0
            state['lowest_price_seen'] = 0.0

        # B. 针对 Grid DCA / 自动网格
        elif strategy_type == 'grid_dca':
            # 重置最近成交的网格索引，强制策略重新扫描当前价格属于哪个区间
            state['last_level_idx'] = -1 
            state['is_trailing_active'] = False
            state['highest_price_seen'] = 0.0
            state['lowest_price_seen'] = 0.0
            
        # C. 针对 Coffin / 箱体战法
        elif strategy_type == 'coffin':
            # 强制进入持仓状态
            state['stage'] = 'IN_POS'
            state['stop_loss_price'] = 0.0
            state['extreme_price'] = float(price)

        # ----------------------------------------
            
        await db.add_log(bot_id, t("manual_warehousing"), price, float(amt_d), 0, float(actual_fee_d), f"Manual Buy (Lev {leverage}x)")
        await db.update_bot_state(bot_id, state, f"{t('msg_manual_buy_success')}: {amt_d}")
        return True

async def execute_manual_close(bot_id):
    lock = get_bot_lock(bot_id)
    async with lock:
        bot_data = await db.get_bot_full_data(bot_id)
        if not bot_data: raise Exception("Bot not found")

        user_lang = bot_data.get('language', 'zh-CN')
        def t(key):
            return TRANSLATIONS.get(user_lang, TRANSLATIONS['zh-CN']).get(key, key)

        state = bot_data['state']
        cfg = bot_data['config']

        cfg['user_id'] = bot_data.get('user_id')
        cfg['api_key'] = bot_data.get('api_key')
        cfg['api_secret'] = bot_data.get('api_secret')
        cfg['exchange_source'] = bot_data.get('exchange_source', 'binance')
        
        # --- 价格获取增强逻辑 ---
        price = RUNTIME_CACHE.get(bot_id, {}).get('market_price', 0)
        if price <= 0:
            try:
                exchange = get_cached_exchange(cfg)
                symbol = bot_data.get('symbol') or cfg.get('symbol')
                ticker = await exchange.fetch_ticker(symbol)
                price = float(ticker['last'])
            except Exception:
                pass
        # -----------------------
        
        if price <= 0: raise Exception(t("err_price_fetch"))
        if float(state.get('position_amt', 0)) == 0: raise Exception(t("no_position"))
        
        pos_amt_d = Decimal(str(state.get('position_amt', 0)))
        avg_price_d = Decimal(str(state.get('avg_price', 0)))
        total_margin_d = Decimal(str(state.get('total_cost', 0)))
        bal_d = Decimal(str(state.get('balance', 0)))
        
        price_d = Decimal(str(price))
        fee_rate_d = Decimal(str(cfg.get('fee_rate', 0.0005)))
        
        close_notional_d = pos_amt_d * price_d
        close_fee_d = close_notional_d * fee_rate_d
        
        direction = state.get('direction', cfg.get('direction', 'long'))
        pnl_d = Decimal(0)
        
        if direction == 'short':
            pnl_d = (avg_price_d - price_d) * pos_amt_d
        else:
            pnl_d = (price_d - avg_price_d) * pos_amt_d
        
        return_amount_d = total_margin_d + pnl_d - close_fee_d
        new_bal_d = bal_d + return_amount_d
        
        realized_profit = float(pnl_d - close_fee_d)
        
        await db.add_log(bot_id, t("log_manual_close"), price, float(pos_amt_d), realized_profit, float(close_fee_d), "Manual Close")
        
        state['balance'] = float(new_bal_d)
        state['position_amt'] = 0.0
        state['avg_price'] = 0.0
        state['total_cost'] = 0.0

        state['last_close_time'] = time.time()
        
        # === 通用状态重置 ===
        state['current_so_index'] = 1
        state['initial_base_price'] = 0.0 
        state['range_top'] = 0.0           
        state['range_bottom'] = 0.0        
        state['is_trailing_active'] = False
        state['last_level_idx'] = -1
        state['lowest_price_seen'] = 0.0
        state['highest_price_seen'] = 0.0
        state['orders'] = [] 

        # === [核心修复] 强制重置 Coffin 策略的状态 ===
        # 防止平仓后 stage 仍为 IN_POS，导致策略卡死
        state['stage'] = 'IDLE'
        state['stop_loss_price'] = 0.0
        state['extreme_price'] = 0.0
        state['breakout_dir'] = None
        state['breakout_price'] = 0.0

        if bot_data.get('strategy_type') == 'periodic':
            state['last_invest_time'] = time.time()
        
        action_after = cfg.get('manual_close_action', 'stop')
        sign = "+" if realized_profit >= 0 else ""
        msg = f"{t('msg_manual_close_success')}, {t('realized_pnl')}: {sign}${realized_profit:.2f}"
        
        if action_after == 'stop':
            await db.toggle_bot_status(bot_id, False)
            msg += f" ({t('stopped')})"
        elif action_after == 'cooldown':
            state['next_trade_time'] = time.time() + 3600
            msg += f" ({t('cooldown_1h')})"
        else:
            state['next_trade_time'] = time.time() + 10
            msg += f" ({t('continue_running')})"
        
        total_profit = float(bot_data.get('current_profit', 0)) + realized_profit
        await db.update_bot_state(bot_id, state, msg, total_profit)
        return realized_profit