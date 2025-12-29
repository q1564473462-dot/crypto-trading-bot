import pandas as pd
import asyncio

class MockExchange:
    def __init__(self, df):
        # df 必须包含: timestamp, open, high, low, close, volume
        self.df = df
        self.current_index = 0
        self.orders = []
        self.balance = 10000.0  # 初始模拟余额
        self.positions = {}     # { 'BTC/USDT': { 'amt': 0.1, 'entry': 50000 } }
        self.leverage = 1

    def set_current_index(self, idx):
        self.current_index = idx

    def get_current_price(self):
        # 获取当前游标的 Close 价格
        if self.current_index >= len(self.df): return 0
        return float(self.df.iloc[self.current_index]['close'])

    async def fetch_ohlcv(self, symbol, timeframe='15m', limit=100):
        # 模拟获取 K 线：返回截止到 current_index 之前的数据
        # 注意：这里简化处理，假设上传的数据周期和请求的周期一致
        # 如果策略请求 4h 而你只上传了 15m，这里需要复杂的重采样逻辑。
        # 目前版本我们假设：用户上传什么周期，策略就用什么周期。
        
        end = self.current_index + 1
        start = max(0, end - limit)
        subset = self.df.iloc[start:end]
        
        # 转换为 ccxt 格式: [[ts, o, h, l, c, v], ...]
        return subset[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()

    async def fetch_ticker(self, symbol):
        price = self.get_current_price()
        return {'last': price, 'ask': price, 'bid': price}

    async def fetch_balance(self):
        return {'USDT': {'free': self.balance, 'used': 0, 'total': self.balance}}
    
    async def fetch_positions(self, symbols=None):
        # 将内部 positions 转换为 ccxt 格式
        res = []
        for sym, data in self.positions.items():
            res.append({
                'symbol': sym,
                'contracts': abs(data['amt']),
                'side': 'long' if data['amt'] > 0 else 'short',
                'entryPrice': data['entry'],
                'unrealizedPnl': (self.get_current_price() - data['entry']) * data['amt']
            })
        return res

    async def create_order(self, symbol, type, side, amount, price=None, params={}):
        # 模拟成交
        exec_price = price if price else self.get_current_price()
        
        # 记录订单
        order = {
            'id': f"mock_{len(self.orders)+1}",
            'symbol': symbol,
            'side': side,
            'amount': amount,
            'price': exec_price,
            'status': 'closed',
            'filled': amount,
            'average': exec_price,
            'timestamp': int(self.df.iloc[self.current_index]['timestamp'])
        }
        self.orders.append(order)
        
        # 更新持仓 (简单的加减仓逻辑)
        curr_pos = self.positions.get(symbol, {'amt': 0, 'entry': 0})
        old_amt = curr_pos['amt']
        
        signed_amt = amount if side == 'buy' else -amount
        new_amt = old_amt + signed_amt
        
        # 计算新均价 (简化版，仅加仓时更新)
        if abs(new_amt) > abs(old_amt): 
            # 加仓
            total_cost = (abs(old_amt) * curr_pos['entry']) + (amount * exec_price)
            new_entry = total_cost / abs(new_amt)
            self.positions[symbol] = {'amt': new_amt, 'entry': new_entry}
        elif new_amt == 0:
            # 平仓
            del self.positions[symbol]
        else:
            # 减仓 (均价不变)
            self.positions[symbol]['amt'] = new_amt
            
        return order