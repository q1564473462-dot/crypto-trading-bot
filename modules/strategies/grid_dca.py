import numpy as np
import time

class GridDCAStrategy:
    """
    Auto Grid DCA 策略 (仅支持 Long/Short)
    [修复]: 余额不足时停止买入并报错
    [新增]: 追踪止盈 (Trailing Take Profit) 功能
    """
    def __init__(self, cfg, t_func=None, now_func=time.time):
        self.cfg = cfg
        self.t = t_func if t_func else (lambda k: k)
        self.now = now_func
        self.capital = float(cfg.get('capital', 1000.0))
        self.grid_count = int(cfg.get('grid_count', 10))
        self.range_percent = float(cfg.get('range_percent', 0.2)) 
        self.tp_target = float(cfg.get('tp_target', 1.5))
        self.trailing_dev = float(cfg.get('trailing_dev', 0.0))
        self.fee_rate = float(cfg.get('fee_rate', 0.0005))
        self.direction = cfg.get('direction', 'long') 
        self.grid_type = cfg.get('grid_type', 'arithmetic')
        # [新增] 读取杠杆
        self.leverage = float(cfg.get('leverage', 1.0))
        if cfg.get('market_type') == 'spot':
            self.leverage = 1.0

        # [新增] 读取止损百分比 (默认为 0，即不启用)
        self.sl_percent = float(cfg.get('stop_loss_percent', 0.0))
        
        # [新增] 交易冷却时间 (默认为 60 秒)
        self.cooldown_seconds = int(cfg.get('cooldown_seconds', 60))
        self.last_close_time = 0

    def get_levels(self, state):
        top = float(state.get('range_top', 0))
        bottom = float(state.get('range_bottom', 0))
        if top <= 0 or bottom <= 0: return []
        if top <= bottom: return []
        
        if self.grid_type == 'geometric':
            return np.geomspace(bottom, top, self.grid_count + 1).tolist()
        else:
            return np.linspace(bottom, top, self.grid_count + 1).tolist()
        
    def analyze_market(self, state, current_price, fvgs=None):
        intent = {'action': 'none', 'cost': 0, 'log_action': '', 'log_note': '', 'status_msg': self.t('status_running')}   

        # --- 1. 自动区间初始化 ---
        if float(state.get('range_top', 0)) == 0:
            if self.direction == 'short':
                # 做空：当前价是底部（进场点），往上是抗单区间
                state['range_bottom'] = current_price
                state['range_top'] = current_price * (1 + self.range_percent)
                state['last_level_idx'] = -1
            else:
                # 做多：当前价是顶部（进场点），往下是抗单区间
                state['range_top'] = current_price
                state['range_bottom'] = current_price * (1 - self.range_percent)
                state['last_level_idx'] = -1

            intent['update_msg'] = True
            intent['status_msg'] = f"🆕 {self.direction.upper()} {self.t('range_info')}: {state['range_bottom']:.2f} - {state['range_top']:.2f}"
            return intent

        levels = self.get_levels(state)
        # 计算每格资金：总资金 / (网格数 + 1)，因为多了首单
        per_grid_cost = self.capital / max(1, self.grid_count + 1)

        active_orders = state.get('orders', [])
        filled_levels = set([o.get('level_idx') for o in active_orders])
        
        pos_amt = float(state.get('position_amt', 0))
        avg_price = float(state.get('avg_price', 0))

        # --- [新增] 0. 首单逻辑：无持仓时立即进场 ---
        if abs(pos_amt) == 0:
            # 🟢 [修改] 从数据库 state 中读取上次平仓时间
            last_close = float(state.get('last_close_time', 0))
            time_since_close = self.now() - last_close
            
            if time_since_close < self.cooldown_seconds:
                remaining = int(self.cooldown_seconds - time_since_close)
                intent['status_msg'] = f"{self.t('status_cooldown')} {remaining}s"
                # 在冷却期间不执行开仓
                return intent
            
            # 做空：从底部(Level 0)开始；做多：从顶部(Level N)开始
            base_idx = 0 if self.direction == 'short' else self.grid_count
            
            intent['action'] = 'buy'
            intent['cost'] = per_grid_cost
            intent['new_level_idx'] = base_idx
            intent['log_action'] = f"{self.t('log_base_order')} ({self.direction})" # 使用翻译
            intent['log_note'] = self.t('base_order_market')
            return intent

        # --- 2. 检查止盈 (基于 ROE) ---
        if abs(pos_amt) > 0 and avg_price > 0:
            # A. 计算币价涨跌幅
            if self.direction == 'short':
                price_move_pct = (avg_price - current_price) / avg_price * 100
            else: 
                price_move_pct = (current_price - avg_price) / avg_price * 100
            
            # B. 计算 ROE (乘杠杆)
            roe_pct = price_move_pct * self.leverage
            
            # C. 扣除手续费损耗
            fee_impact_pct = self.fee_rate * 2 * 100 * self.leverage
            net_pnl_pct = roe_pct - fee_impact_pct

            # === [新增] 检查止损 (Stop Loss) ===
            if self.sl_percent > 0 and roe_pct < -self.sl_percent:
                intent['action'] = 'sell'
                intent['log_action'] = self.t('log_stop_loss')
                intent['log_note'] = f"{self.t('sl_hit')}: {roe_pct:.2f}% (ROE)"
                
                # 止损后重置区间
                intent['reset_range'] = True 
                intent['log_note'] += self.t('interval_reset')
                
                # [新增] 记录平仓时间，触发冷却
                self.last_close_time = self.now()
                return intent

            # 获取追踪状态
            is_trailing = state.get('is_trailing_active', False)
            reached_tp = (net_pnl_pct >= self.tp_target)

            # Case A: 达到目标且未激活追踪
            if reached_tp and not is_trailing:
                if self.trailing_dev > 0:
                    intent['action'] = 'update_trail'
                    intent['log_note'] = f"TP Trigger: {net_pnl_pct:.2f}% (ROE)"
                    intent['status_msg'] = self.t('status_insufficient_balance')
                    return intent
                else:
                    intent['action'] = 'sell' 
                    intent['log_action'] = self.t('log_take_profit')
                    intent['log_note'] = f"ROI: {net_pnl_pct:.2f}%"
                    intent['reset_range'] = True
                    intent['log_note'] += self.t('interval_reset')
                    return intent
            
            # Case B: 已在追踪中
            if is_trailing:
                should_sell = False
                high_seen = float(state.get('highest_price_seen', 0) or 0)
                low_seen = float(state.get('lowest_price_seen', 0) or 0)

                if self.direction == 'long':
                    if high_seen == 0: high_seen = current_price
                    price_drawdown = (high_seen - current_price) / high_seen * 100
                    if price_drawdown >= self.trailing_dev: should_sell = True
                    if current_price > high_seen:
                        intent['action'] = 'update_trail'
                        return intent 
                else: # Short
                    if low_seen <= 0: low_seen = current_price
                    price_rebound = (current_price - low_seen) / low_seen * 100
                    if price_rebound >= self.trailing_dev: should_sell = True
                    if current_price < low_seen:
                        intent['action'] = 'update_trail'
                        return intent

                if should_sell:
                    intent['action'] = 'sell'
                    intent['log_action'] = self.t('tracking_profits')
                    intent['log_note'] = f"Trailing Hit. ROE: {net_pnl_pct:.2f}%"
                    intent['reset_range'] = True
                    intent['log_note'] += self.t('interval_reset')
                    return intent

        # --- 3. 检查补仓 (独立网格逻辑) ---
        if not state.get('is_trailing_active', False):
            # [新增] 防止手动加仓后立即在同一位置重复开单
            # 逻辑：检查是否有“最近一次”同方向的订单，且价格极度接近
            last_orders = state.get('orders', [])
            if last_orders:
                last_order = last_orders[-1]
                # 如果最后一单发生在一分钟内，且价格差异小于 0.1%
                time_diff = self.now() - last_order.get('time', 0)
                price_diff = abs(current_price - last_order.get('price', 0)) / last_order.get('price', 1)
                
                if time_diff < 60 and price_diff < 0.001:
                    intent['status_msg'] = self.t('just_traded_waiting_for_deviation')
                    return intent
            best_target_idx = -1
            
            if self.direction == 'short':
                for idx, target_price in enumerate(levels):
                    if idx in filled_levels: continue
                    # 做空：价格上涨触碰上面的网格线才补仓
                    if current_price >= target_price:
                        if idx > best_target_idx: best_target_idx = idx
            else:
                for idx, target_price in enumerate(levels):
                    if idx in filled_levels: continue
                    # 做多：价格下跌触碰下面的网格线才补仓
                    if current_price <= target_price:
                        if idx > best_target_idx: best_target_idx = idx 
            
            # 只有当找到比当前更优的网格，且不是首单（首单已在上面处理）时才开仓
            # 这里加一个防止重复开首单的保险，虽然 filled_levels 应该已经处理了
            if best_target_idx != -1:
                balance = float(state.get('balance', 0))
                if balance < per_grid_cost:
                    intent['status_msg'] = self.t('insufficient_balance_stop_replenishment')
                    return intent
                    
                intent['action'] = 'buy'
                intent['cost'] = per_grid_cost
                intent['log_action'] = f"{self.t('grid_buy')} L{best_target_idx}"
                intent['log_note'] = f"Price: {levels[best_target_idx]:.2f}"
                intent['new_level_idx'] = best_target_idx
                return intent

        return intent

    def generate_ladder(self, base_price=0, current_so=-1, market_price=0):
        # 1. 基础数据准备
        top = 0
        bottom = 0
        
        if base_price > 0:
            top = base_price
            if self.direction == 'short':
                bottom = top / (1 + self.range_percent)
            else:
                bottom = top * (1 - self.range_percent)
        else:
            if market_price <= 0: return []
            if self.direction == 'short':
                bottom = market_price
                top = bottom * (1 + self.range_percent)
            else:
                top = market_price
                bottom = top * (1 - self.range_percent)

        # 2. 生成网格线
        if getattr(self, 'grid_type', 'arithmetic') == 'geometric':
            levels = np.geomspace(bottom, top, self.grid_count + 1).tolist()
        else:
            levels = np.linspace(bottom, top, self.grid_count + 1).tolist()
            
        ladder = []  
        per_cost = self.capital / max(1, self.grid_count + 1)
        
        # 3. 生成状态列表
        for i, price in enumerate(levels):
            real_idx = i
            status = self.t('status_waiting')
            
            # === [核心修复] 优先判断真实成交进度 ===
            # current_so 对应的是数据库里的 last_level_idx
            # 如果这一格的索引 <= 当前已成交的索引，那就肯定是“已成交”
            if current_so >= 0:
                is_filled = False
                
                if self.direction == 'long':
                    # 做多：从上往下买 (Base=Max Index)。
                    # 比如总共5格，首单在L5。L5已成交，L0-L4等待。
                    # 如果跌到L4补仓，则L4, L5已成交。
                    if real_idx >= current_so:
                        is_filled = True
                else:
                    # 做空：从下往上买 (Base=L0)。
                    # 首单在L0。如果涨到L1补仓，则L0, L1已成交。
                    if real_idx <= current_so:
                        is_filled = True

                if is_filled:
                    status = self.t('status_filled')
            else:
                # 只有在还没持仓 (-1) 的时候，才用价格去估算预览
                if self.direction == 'short':
                    if price <= market_price: status = self.t('status_filled') + self.t('first_order_area')
                else:
                    if price >= market_price: status = self.t('status_filled') + self.t('first_order_area')
                
            ladder.append({
                "so": f"{self.t('grid')} L{real_idx}",
                "price": price,
                "amount": per_cost,
                "total": 0, 
                "drop": 0, 
                "status": status
            })
            
        return ladder