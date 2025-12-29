import numpy as np
import pandas as pd
import time

class CoffinStrategy:
    """
    ⚰️ Coffin 趋势战法 (完整修复版)
    包含: 
    1. 强制 EMA50 趋势过滤 (解决逆势亏损)
    2. 收盘价确认突破 (解决插针假突破)
    3. 反弹确认 (解决接飞刀)
    4. 状态锁修复 (解决重复开单)
    """
    def __init__(self, cfg, t_func=None, now_func=time.time):
        self.cfg = cfg
        self.t = t_func if t_func else (lambda k: k)
        self.now = now_func
        # 基础配置
        self.capital = float(cfg.get('capital', 1000.0))
        self.order_amount = float(cfg.get('order_amount', 0.0))
        self.direction = cfg.get('direction', 'long')
        
        self.leverage = float(cfg.get('leverage', 1.0))
        if cfg.get('market_type') == 'spot':
            self.leverage = 1.0
        
        # Coffin 参数
        self.lookback = int(cfg.get('coffin_lookback', 3))
        self.break_even_trigger = float(cfg.get('be_trigger', 0.5)) / 100.0 
        self.trailing_gap = float(cfg.get('trailing_gap', 1.0)) / 100.0 
        self.retest_tolerance = float(cfg.get('retest_tolerance', 0.1)) / 100.0 
        
        # 冷却时间
        self.cooldown_seconds = int(cfg.get('cooldown_seconds', 60))
    
    # [新增] 必须加这个辅助函数来计算 EMA
    def _calc_ema(self, prices, period=50):
        if len(prices) < period: return 0
        return float(pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1])

    def _get_coffin_box(self, ohlcv_data):
        if not ohlcv_data or len(ohlcv_data) < 5:
            return None, None, None
        
        completed = ohlcv_data[:-1]
        pivot_found = False
        pivot_type = None 
        c1_idx = -1

        for i in range(len(completed) - 2, 0, -1):
            curr = completed[i]
            prev = completed[i-1]
            next_c = completed[i+1] 
            
            if curr[2] >= prev[2] and curr[2] >= next_c[2]:
                pivot_type = 'top'
                c1_idx = i
                pivot_found = True
                break
            
            if curr[3] <= prev[3] and curr[3] <= next_c[3]:
                pivot_type = 'bottom'
                c1_idx = i
                pivot_found = True
                break
        
        if not pivot_found:
            return None, None, None

        c1 = completed[c1_idx]     
        c2 = completed[c1_idx + 1]
        
        c1_body_top = max(c1[1], c1[4])
        c1_body_bot = min(c1[1], c1[4])
        c2_body_top = max(c2[1], c2[4])
        c2_body_bot = min(c2[1], c2[4])
        
        box_top = 0.0
        box_bottom = 0.0

        if pivot_type == 'top':
            y1 = c1_body_top
            y2 = c2_body_bot
            box_top = max(y1, y2)
            box_bottom = min(y1, y2)
            
        elif pivot_type == 'bottom':
            y1 = c1_body_bot
            y2 = c2_body_top
            box_top = max(y1, y2)
            box_bottom = min(y1, y2)

        coffin_id = c1[0]
        return box_top, box_bottom, coffin_id

    def analyze_market(self, state, current_price, extra_data=None):
        intent = {'action': 'none', 'log_note': '', 'status_msg': self.t('status_monitoring')}   

        pos_amt = float(state.get('position_amt', 0))
        stage = state.get('stage', 'IDLE')
        avg_price = float(state.get('avg_price', 0))
        
        # === [修正1] 只要有持仓，强制修正状态为 IN_POS (防止闪烁) ===
        if abs(pos_amt) > 0:
            state['stage'] = 'IN_POS'
            stage = 'IN_POS'

        # 1. 预处理数据
        if not extra_data or 'ohlcv_5m' not in extra_data or 'ohlcv_15m' not in extra_data:
            if stage != 'IN_POS':
                intent['status_msg'] = "⚠️ " + self.t("waiting_for_kline")
                return intent 
        else:
            top_5m, bot_5m, cid_5m = self._get_coffin_box(extra_data['ohlcv_5m'])
            top_15m, bot_15m, cid_15m = self._get_coffin_box(extra_data['ohlcv_15m'])
            
            if top_5m and top_15m:
                state['coffin_5m'] = {'top': top_5m, 'bottom': bot_5m, 'id': cid_5m}
                state['coffin_15m'] = {'top': top_15m, 'bottom': bot_15m, 'id': cid_15m}

        # === 状态 1: 持仓中 (IN_POS) ===
        if stage == 'IN_POS':
            if abs(pos_amt) == 0:
                state['stage'] = 'IDLE'
                # 重置相关的追踪变量，防止逻辑残留
                state['stop_loss_price'] = 0.0
                state['extreme_price'] = 0.0
                intent['status_msg'] = "⚠️ Order Rejected/Closed, Resetting to IDLE"
                return intent
            
            current_sl = float(state.get('stop_loss_price', 0))
            extreme_price = float(state.get('extreme_price', current_price))
            
            current_dir = state.get('direction', self.cfg.get('direction', 'long'))
            is_long = (current_dir == 'long')
            
            # 更新极值
            if is_long: extreme_price = max(extreme_price, current_price)
            else: extreme_price = min(extreme_price, current_price) if extreme_price > 0 else current_price
            state['extreme_price'] = extreme_price

            # --- Level 2: 保本损 (BE) ---
            entry_price = avg_price
            if entry_price > 0:
                price_move_pct = (current_price - entry_price) / entry_price if is_long else (entry_price - current_price) / entry_price
                roe_pct = price_move_pct * self.leverage
                
                if roe_pct > self.break_even_trigger:
                    be_price = entry_price * 1.001 if is_long else entry_price * 0.999 
                    if is_long and be_price > current_sl:
                        current_sl = be_price
                        intent['log_note'] = f"{self.t('trigger_be')} (ROE {roe_pct*100:.1f}%)"
                    elif not is_long and (current_sl == 0 or be_price < current_sl):
                        current_sl = be_price
                        intent['log_note'] = f"{self.t('trigger_be')} (ROE {roe_pct*100:.1f}%)"

            # --- Level 3: 追踪止盈 (Trailing) ---
            if is_long:
                trail_sl = extreme_price * (1 - self.trailing_gap)
                if trail_sl > current_sl:
                    current_sl = trail_sl
                    intent['log_note'] = self.t("trailing_sl_up")
            else:
                trail_sl = extreme_price * (1 + self.trailing_gap)
                if current_sl == 0 or trail_sl < current_sl:
                    current_sl = trail_sl
                    intent['log_note'] = self.t("trailing_sl_down")

            state['stop_loss_price'] = current_sl
            
            # 平仓检查
            should_close = False
            if current_sl > 0:
                if is_long and current_price <= current_sl: should_close = True
                if not is_long and current_price >= current_sl: should_close = True
            
            if should_close:
                intent['action'] = 'sell'
                intent['log_action'] = self.t('log_stop_loss')
                if avg_price > 0:
                    pnl_pct = (current_price - avg_price)/avg_price if is_long else (avg_price - current_price)/avg_price
                    if pnl_pct > 0: intent['log_action'] = self.t('log_take_profit')

                intent['reset_coffin'] = True 
                return intent
            
            intent['update_msg'] = True
            dir_text = "LONG" if is_long else "SHORT"
            intent['status_msg'] = f"{self.t('status_running')} ({dir_text}) | SL: {current_sl:.2f}"
            return intent

        # === 状态 2: 空闲扫描 (IDLE) ===
        if stage == 'IDLE':
            # [检查 ID 锁] 避免重复交易同一个棺材
            last_traded_id = state.get('last_traded_coffin_id')
            current_id = state.get('coffin_15m', {}).get('id')

            if last_traded_id == current_id:
                intent['status_msg'] = f"😴 {self.t('scanning')} (Coffin Done)"
                return intent
            
            top_15m = state.get('coffin_15m', {}).get('top', 0)
            bot_15m = state.get('coffin_15m', {}).get('bottom', 0)
            
            if not top_15m: return intent

            # === [修正2] 强制 EMA 趋势过滤 (核心) ===
            closes_15m = [x[4] for x in extra_data['ohlcv_15m']]
            ema_50 = self._calc_ema(closes_15m, 50) 
            
            last_close = extra_data['ohlcv_15m'][-2][4] 
            
            # 只有收盘价和现价都突破才算
            is_break_up = last_close > top_15m and current_price > top_15m
            is_break_down = last_close < bot_15m and current_price < bot_15m
            
            # ⛔️ 强制过滤：逆势直接封杀
            if ema_50 > 0:
                if is_break_up and current_price < ema_50:
                    is_break_up = False 
                    intent['status_msg'] = f"📉 Filtered: Price < EMA50 ({ema_50:.1f})"
                
                if is_break_down and current_price > ema_50:
                    is_break_down = False 
                    intent['status_msg'] = f"📈 Filtered: Price > EMA50 ({ema_50:.1f})"

            target_dir = None
            if is_break_up and self.direction in ['long', 'both']:
                target_dir = 'long'
            elif is_break_down and self.direction in ['short', 'both']:
                target_dir = 'short'
            
            if target_dir:
                state['stage'] = 'BREAKOUT'
                state['breakout_dir'] = target_dir
                state['breakout_price'] = current_price
                intent['status_msg'] = f"🚀 Detected {target_dir} Breakout"
                intent['update_msg'] = True
            else:
                intent['status_msg'] = f"👀 {self.t('scanning')} (EMA50: {ema_50:.1f})"
            
            return intent

        # === 状态 3: 等待回踩 (BREAKOUT / RETEST) ===
        if stage in ['BREAKOUT', 'RETEST']:
            target_dir = state.get('breakout_dir')
            box_edge = state.get('coffin_5m', {}).get('top', 0) if target_dir == 'long' else state.get('coffin_5m', {}).get('bottom', 0)
            
            dist_pct = abs(current_price - box_edge) / box_edge
            is_near_edge = dist_pct <= self.retest_tolerance
            
            if is_near_edge:
                # 反弹确认
                curr_open = extra_data['ohlcv_5m'][-1][1]
                is_bouncing = False
                if target_dir == 'long' and current_price > curr_open: is_bouncing = True
                if target_dir == 'short' and current_price < curr_open: is_bouncing = True
                
                if is_bouncing:
                    intent['action'] = 'buy'
                    intent['cost'] = self.order_amount if self.order_amount > 0 else self.capital
                    intent['log_action'] = f"Entry {target_dir}"
                    
                    # === [修正3] 下单瞬间锁死状态并记录ID ===
                    state['stage'] = 'IN_POS' 
                    state['last_traded_coffin_id'] = state.get('coffin_15m', {}).get('id')
                    state['direction'] = target_dir
                    state['stop_loss_price'] = box_edge * 0.99 if target_dir == 'long' else box_edge * 1.01
                    
                    intent['update_msg'] = True
                    return intent
                else:
                    intent['status_msg'] = f"⏳ Waiting for bounce ({target_dir})"
                    return intent
            
            intent['status_msg'] = f"Waiting Retest {dist_pct*100:.2f}%"
            state['stage'] = 'RETEST'
            intent['update_msg'] = True
            
        return intent

    def generate_ladder(self, *args, **kwargs):
        return []