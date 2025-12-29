import pandas as pd
import numpy as np
import time
import asyncio  # 引入 asyncio

class FVGStrategy:
    """
    FVG + DCA 策略 (Asyncio Version)
    """
    def __init__(self, cfg, t_func=None, now_func=time.time):
        self.cfg = cfg
        self.t = t_func if t_func else (lambda k: k)
        self.now = now_func
        self.direction = cfg.get('direction', 'long')
        self.vol_scale = float(cfg.get('volume_scale', 1.0))
        self.step_scale = float(cfg.get('step_scale', 1.0))
        self.step_pct = float(cfg.get('step_percent', 1.0)) / 100.0
        self.max_orders = int(cfg.get('max_orders', 7))
        self.capital = float(cfg.get('capital', 1000.0))
        self.use_fvg = cfg.get('use_fvg', False)
        
        # [新增] 读取杠杆和费率，用于计算 ROE
        self.leverage = float(cfg.get('leverage', 1.0))
        if cfg.get('market_type') == 'spot':
            self.leverage = 1.0
        self.fee_rate = float(cfg.get('fee_rate', 0.0005))

        self.cooldown_seconds = int(cfg.get('cooldown_seconds', 60))
        
        if self.vol_scale == 1.0:
            multiplier = float(self.max_orders)
        else:
            multiplier = (1.0 - pow(self.vol_scale, self.max_orders)) / (1.0 - self.vol_scale)
        self.base_order_size = self.capital / (multiplier if multiplier else 1)

    # [修改点] 改为 async，并且 await exchange.fetch_ohlcv
    async def find_fvgs(self, exchange, symbol, timeframe_label, limit_count=3):
        try:
            # 异步获取 K 线
            bars = await exchange.fetch_ohlcv(symbol, timeframe=timeframe_label, limit=100)
            if not bars: return []
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        except Exception:
            return []

        if len(df) < 5: return []
        
        df['prev_high'] = df['high'].shift(1) 
        df['prev_low'] = df['low'].shift(1)   
        df['high_s3'] = df['high'].shift(3)   
        df['low_s3'] = df['low'].shift(3)     
        
        lookback = min(len(df), 100)
        subset = df.iloc[-lookback:].copy()
        
        fvgs = []
        
        if self.direction == 'long':
            candidates = subset[subset['high_s3'] < subset['prev_low']]
            for idx, row in candidates.iloc[::-1].iterrows():
                if len(fvgs) >= limit_count: break
                top = row['prev_low']
                bottom = row['high_s3']
                future_bars = subset.loc[idx+1:]
                if future_bars.empty or not (future_bars['low'] <= top).any():
                    fvgs.append({'top': top, 'bottom': bottom, 'tf': timeframe_label})

        elif self.direction == 'short':
            candidates = subset[subset['low_s3'] > subset['prev_high']]
            for idx, row in candidates.iloc[::-1].iterrows():
                if len(fvgs) >= limit_count: break
                top = row['low_s3']
                bottom = row['prev_high']
                future_bars = subset.loc[idx+1:]
                if future_bars.empty or not (future_bars['high'] >= bottom).any():
                     fvgs.append({'top': top, 'bottom': bottom, 'tf': timeframe_label})
        
        return fvgs

    def analyze_market(self, state, current_price, fvgs):
        intent = {'action': 'none', 'cost': 0, 'log_action': '', 'log_note': '', 'status_msg': self.t('status_monitoring')}
        is_long = (self.direction == 'long')
        pos_amt = float(state.get('position_amt', 0))
        
        # 1. 无持仓：检查是否需要开首单
        if pos_amt == 0:
            last_close = float(state.get('last_close_time', 0))
            time_since_close = self.now() - last_close
            
            if time_since_close < self.cooldown_seconds:
                remaining = int(self.cooldown_seconds - time_since_close)
                intent['status_msg'] = f"{self.t('status_cooldown')} {remaining}s"
                # 冷却中，直接返回
                return intent
            
            _, cost, _, _ = self.calculate_next_buy(current_price, 1, [])
            intent['action'] = 'buy'
            intent['cost'] = cost
            intent['is_base'] = True
            intent['log_action'] = f"{self.t('log_base_order')}({self.direction})"
            intent['log_note'] = self.t('base_order_market') or "Base Order"
            return intent

        # [核心修改] 统一计算 ROE (本金收益率)
        avg_price = float(state.get('avg_price', 0))
        roe_pct = 0.0
        
        if avg_price > 0:
            if is_long:
                price_move_pct = (current_price - avg_price) / avg_price * 100 
            else:
                price_move_pct = (avg_price - current_price) / avg_price * 100
            
            # 乘杠杆得到 ROE
            roe_pct = price_move_pct * self.leverage
            # 扣除手续费估算 (开+平=2次)
            fee_impact = self.fee_rate * 2 * 100 * self.leverage
            roe_pct -= fee_impact

        # 2. 有持仓：检查止损 (基于 ROE)
        sl_pct = float(self.cfg.get('stop_loss_percent', 0))
        
        if sl_pct > 0 and avg_price > 0:
            # 如果 ROE 亏损超过设定的 sl_pct (例如 -15%)
            if roe_pct < -sl_pct:
                intent['action'] = 'sell'
                intent['log_action'] = {self.t('log_stop_loss')}
                intent['log_note'] = f"{self.t('sl_hit')}: {roe_pct:.2f}% (ROE)"
                return intent

        # 3. 检查止盈与追踪 (基于 ROE)
        tp_target = float(self.cfg.get('tp_target', 1.2))
        trailing_dev = float(self.cfg.get('trailing_dev', 0.2)) # 这里保持为价格回撤，避免噪音
        is_trailing = state.get('is_trailing_active', False)
        
        # 只要 ROE 达到目标，就视为达到止盈条件
        reached_tp = (roe_pct >= tp_target)

        # Case A: 达到目标 (ROE) 且未激活追踪
        if reached_tp and not is_trailing:
            intent['action'] = 'update_trail'
            intent['log_note'] = f"Target Hit: {roe_pct:.2f}% (ROE)"
            intent['status_msg'] = f"🔥 {self.t('trigger_take_profit_trailing')}"
            return intent
            
        # Case B: 已在追踪中 (逻辑保持：价格反转即止盈)
        if is_trailing:
            should_sell = False
            high_seen = float(state.get('highest_price_seen', 0) or 0)
            low_seen = float(state.get('lowest_price_seen', 0) or 0)
            
            if is_long:
                if high_seen == 0: high_seen = current_price
                # 价格从最高点回撤
                price_drawdown = (high_seen - current_price) / high_seen * 100
                if price_drawdown >= trailing_dev: should_sell = True
            else:
                if low_seen <= 0: low_seen = current_price
                # 价格从最低点反弹
                price_rebound = (current_price - low_seen) / low_seen * 100
                if price_rebound >= trailing_dev: should_sell = True
            
            if should_sell:
                intent['action'] = 'sell'
                intent['log_action'] = self.t('log_take_profit')
                intent['log_note'] = f"{self.t('trailing_hit')}: {roe_pct:.2f}%"
                return intent
            
            # 更新极值
            update_extreme = False
            if is_long:
                if current_price > high_seen: update_extreme = True
            else:
                if current_price < low_seen: update_extreme = True
                
            if update_extreme:
                intent['action'] = 'update_trail'
                return intent

        # 4. 检查补仓 (DCA)
        current_so = int(state.get('current_so_index', 1))
        # 只有在未触发追踪止盈的情况下才补仓
        if current_so <= self.max_orders and not is_trailing:
            valid_fvgs = []
            if fvgs:
                for f in fvgs:
                    if is_long and current_price < f['bottom']: continue
                    if not is_long and current_price > f['top']: continue
                    valid_fvgs.append(f)

            price_trigger, cost, _, src = self.calculate_next_buy(state.get('initial_base_price', avg_price), current_so, valid_fvgs)
            should_dca = False
            if is_long and current_price <= price_trigger: should_dca = True
            if not is_long and current_price >= price_trigger: should_dca = True
            
            if should_dca:
                intent['action'] = 'buy'
                intent['cost'] = cost
                intent['is_base'] = False
                intent['log_action'] = f"{self.t('log_dca_buy')} #{current_so}"
                intent['log_note'] = f"{self.t('source')}: {src}"
                return intent
                
        return intent
    
    def get_cumulative_drop(self, order_index):
        if order_index <= 1: return 0.0
        effective_so_count = order_index - 1
        if self.step_scale == 1.0:
            return self.step_pct * effective_so_count
        return self.step_pct * (1 - pow(self.step_scale, effective_so_count)) / (1 - self.step_scale)

    def calculate_next_buy(self, base_entry_price, current_order_index, consolidated_fvgs):
        amount = self.base_order_size * pow(self.vol_scale, current_order_index - 1)
        target_percent = self.get_cumulative_drop(current_order_index)
        trigger_price = 0.0
        
        if self.direction == 'long':
            price_target = base_entry_price * (1.0 - target_percent)
            prev_percent = self.get_cumulative_drop(current_order_index - 1)
            prev_target = base_entry_price * (1.0 - prev_percent)
            trigger_price = price_target
            fvg_search_top = prev_target
            fvg_search_bottom = price_target
        else: 
            price_target = base_entry_price * (1.0 + target_percent)
            prev_percent = self.get_cumulative_drop(current_order_index - 1)
            prev_target = base_entry_price * (1.0 + prev_percent)
            trigger_price = price_target
            fvg_search_top = price_target
            fvg_search_bottom = prev_target

        found_fvg = False
        best_src = "Step"
        
        if current_order_index > 1 and self.use_fvg and consolidated_fvgs:
            best_fvg_price = None
            for fvg in consolidated_fvgs:
                f_top = fvg['top']
                f_bottom = fvg['bottom']
                if self.direction == 'long':
                    if f_top <= fvg_search_top and f_top >= fvg_search_bottom:
                        if best_fvg_price is None or f_top > best_fvg_price:
                            best_fvg_price = f_top
                            best_src = fvg['tf']
                else:
                    if f_bottom >= fvg_search_bottom and f_bottom <= fvg_search_top:
                        if best_fvg_price is None or f_bottom < best_fvg_price:
                            best_fvg_price = f_bottom
                            best_src = fvg['tf']
            if best_fvg_price is not None:
                trigger_price = best_fvg_price
                found_fvg = True
                best_src = f"FVG-{best_src}"
                
        return trigger_price, amount, found_fvg, best_src

    def generate_ladder(self, base_price, current_so_idx, market_price=0):
        ladder = []
        anchor = base_price if base_price > 0 else market_price
        if anchor <= 0: return []
        cumulative_cost = 0.0
        
        for i in range(1, self.max_orders + 1):
            price, amount, _, _ = self.calculate_next_buy(anchor, i, [])
            cumulative_cost += amount
            status = self.t("status_waiting")
            
            if i < current_so_idx: 
                status = self.t("status_filled")
            elif i == current_so_idx: 
                # [修改] 将这里从 status_running 改为 status_order_pending
                status = self.t("status_order_pending")
            
            pct_diff = 0
            if anchor > 0:
                pct_diff = (price - anchor) / anchor * 100
                
            ladder.append({
                "so": i, "price": price, "amount": amount,
                "total": cumulative_cost, "drop": pct_diff, "status": status
            })
        return ladder