import time

class PeriodicStrategy:
    """
    定投策略 (Periodic Investment)
    逻辑：
    1. 每隔固定时间 (interval_hours) 买入固定金额 (invest_amount)。
    2. 支持做多 (Long) 或做空 (Short)。
    3. 价格过滤器：高于/低于某价格停止定投。
    4. 无追踪止盈，纯积累筹码。
    """
    def __init__(self, cfg, t_func=None, now_func=time.time):
        self.cfg = cfg
        self.t = t_func if t_func else (lambda k: k)
        self.now = now_func
        
        self.direction = cfg.get('direction', 'long')
        self.leverage = float(cfg.get('leverage', 1.0))
        # 强制限制杠杆最大 3倍
        if self.leverage > 3.0: self.leverage = 3.0
        
        self.interval_minutes = float(cfg.get('interval_minutes', 60.0))
        self.invest_amount = float(cfg.get('invest_amount', 10.0))   # 默认10U
        self.price_limit = float(cfg.get('price_limit', 0.0))        # 0 代表不限制

    def analyze_market(self, state, current_price, extra_data=None):
        intent = {'action': 'none', 'log_note': '', 'status_msg': self.t('status_monitoring')} 

        next_trade_time = float(state.get('next_trade_time', 0))
        now = self.now()
        
        if now < next_trade_time:
            remaining = int(next_trade_time - now)
            # 显示冷却倒计时
            intent['status_msg'] = f"🧊 {self.t('status_cooldown')} {remaining}s"
            return intent  
        
        # 1. 检查资金是否足够 (虽然 bot_manager 会再次检查，但这里可以先预判)
        balance = float(state.get('balance', 0))
        # 估算需要保证金 = 投资额 / 杠杆
        required_margin = self.invest_amount
        
        if balance < required_margin:
            intent['status_msg'] = self.t('status_insufficient_balance')
            return intent

        # 2. 检查价格限制
        # 做多：如果现价 > 设置的上限，不买
        if self.direction == 'long' and self.price_limit > 0 and current_price > self.price_limit:
            intent['status_msg'] = f"⏸️ {self.t('price_too_high')} (> {self.price_limit})"
            return intent
            
        # 做空：如果现价 < 设置的下限，不空
        if self.direction == 'short' and self.price_limit > 0 and current_price < self.price_limit:
            intent['status_msg'] = f"⏸️ {self.t('price_too_low')} (< {self.price_limit})"
            return intent

        # 3. 检查时间间隔
        last_invest_time = float(state.get('last_invest_time', 0))
        now = self.now()
        interval_seconds = self.interval_minutes * 60
        
        if last_invest_time == 0:
            should_buy = True
        elif (now - last_invest_time) >= interval_seconds:
            should_buy = True
        else:
            should_buy = False
            # 计算倒计时用于显示
            remaining = int(interval_seconds - (now - last_invest_time))
            # [修改] 显示逻辑优化，如果剩余时间很短，只显示分钟和秒
            if remaining < 3600:
                mins = remaining // 60
                secs = remaining % 60
                intent['status_msg'] = f"⏳ {self.t('waiting_interval')}: {mins}m {secs}s"
            else:
                hours = remaining // 3600
                mins = (remaining % 3600) // 60
                intent['status_msg'] = f"⏳ {self.t('waiting_interval')}: {hours}h {mins}m"

        if should_buy:
            intent['action'] = 'buy'
            margin_cost = self.invest_amount
            
            intent['cost'] = margin_cost
            intent['log_action'] = self.t('periodic_buy')
            # [修改] 日志记录改为分钟
            intent['log_note'] = f"Interval: {self.interval_minutes}m"
            
            state['last_invest_time'] = now 
            intent['update_msg'] = True 

        return intent

    def generate_ladder(self, *args, **kwargs):
        # 定投没有网格梯子
        return []