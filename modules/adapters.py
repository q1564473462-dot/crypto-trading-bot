import aiohttp
import asyncio
import json
import time
import hmac
import hashlib
import urllib.parse

class ExchangeAdapter:
    """交易所适配器基类"""
    def __init__(self):
        self.source_name = "unknown"

    async def fetch_price(self, symbol):
        raise NotImplementedError
    
    async def fetch_ticker(self, symbol):
        raise NotImplementedError

    async def fetch_ohlcv(self, symbol, timeframe, limit=100):
        raise NotImplementedError

    async def fetch_symbols(self):
        raise NotImplementedError

    async def close(self):
        pass

class PionexAdapter(ExchangeAdapter):
    """
    Pionex 官方 REST API 适配器 (已完善签名验证)
    API 文档: https://pionex-doc.gitbook.io/apidocs
    """
    def __init__(self, api_key=None, api_secret=None, market_type='spot'):
        super().__init__()
        self.source_name = "pionex"
        self.base_url = "https://api.pionex.com"
        self.session = None
        self.api_key = api_key
        self.api_secret = api_secret

        self.pionex_type = 'PERP' if market_type == 'future' else 'SPOT'

    async def _get_session(self):
        if self.session is None or self.session.closed:
            # trust_env=True 允许读取服务器的环境变量代理设置
            self.session = aiohttp.ClientSession(trust_env=True)
        return self.session

    def _symbol_to_pionex(self, symbol):
        """ 将 BTC/USDT 转换为 BTC_USDT """
        return symbol.upper().replace('/', '_')

    def _symbol_from_pionex(self, pionex_symbol):
        """ 将 BTC_USDT 转换为 BTC/USDT """
        return pionex_symbol.replace('_', '/')

    def _map_timeframe(self, tf):
        mappings = {
            '1m': '1M', '3m': '3M', '5m': '5M', '15m': '15M', 
            '30m': '30M', '1h': '60M', '4h': '4H', '8h': '8H', 
            '12h': '12H', '1d': '1D', '7d': '7D', '1w': '7D',
            '1M': '30D'
        }
        return mappings.get(tf, '15M')

    def _generate_signature(self, method, endpoint, params, json_body=None):
        """
        Pionex 签名算法:
        Signature = HMAC-SHA256(API_SECRET, METHOD + PATH + ? + SORTED_QUERY + BODY)
        """
        # 1. 对参数进行 ASCII 排序
        sorted_params = sorted(params.items(), key=lambda d: d[0])
        query_string = urllib.parse.urlencode(sorted_params)
        
        # 2. 拼接签名原串
        # 注意: Pionex 要求 endpoint (如 /api/v1/...) 后面紧跟 ? 然后是参数
        to_sign = f"{method}{endpoint}?{query_string}"
        
        if method in ['POST', 'DELETE'] and json_body:
            # 分隔符必须紧凑 (separators=(',', ':'))
            to_sign += json.dumps(json_body, separators=(',', ':'))
            
        # 3. 计算 HMAC SHA256
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            to_sign.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature

    async def _request(self, method, endpoint, params=None, data=None):
        """ 统一请求封装，自动处理签名 """
        if params is None: params = {}
        
        # 1. 注入必需的时间戳 (毫秒)
        params['timestamp'] = int(time.time() * 1000)
        
        headers = {
            'Content-Type': 'application/json'
        }
        
        # 2. 如果配置了 Key，则添加签名
        if self.api_key and self.api_secret:
            signature = self._generate_signature(method, endpoint, params, data)
            headers['PIONEX-KEY'] = self.api_key
            headers['PIONEX-SIGNATURE'] = signature
        
        # 3. 构建最终 URL (手动构建以确保顺序与签名一致)
        sorted_params = sorted(params.items(), key=lambda d: d[0])
        query_string = urllib.parse.urlencode(sorted_params)
        url = f"{self.base_url}{endpoint}?{query_string}"
        
        session = await self._get_session()
        
        try:
            if method == 'GET':
                async with session.get(url, headers=headers, timeout=10) as resp:
                    return await self._handle_response(resp, endpoint)
            elif method == 'POST':
                async with session.post(url, headers=headers, json=data, timeout=10) as resp:
                    return await self._handle_response(resp, endpoint)
        except Exception as e:
            print(f"[Pionex] Request Error ({endpoint}): {e}")
        return None

    async def _handle_response(self, resp, endpoint):
        if resp.status != 200:
            text = await resp.text()
            print(f"[Pionex] HTTP {resp.status} ({endpoint}): {text}")
            return None
            
        data = await resp.json()
        
        # Pionex 成功通常返回 "result": true
        if not data.get('result', False):
            # 有些公共接口可能结构不一样，这里做个简单兼容
            if 'data' not in data:
                 print(f"[Pionex] API Logic Error ({endpoint}): {data}")
        return data

    async def fetch_price(self, symbol):
        """ 获取最新成交价 """
        params = {
            'type': self.pionex_type
        }

        # 获取所有 tickers
        data = await self._request('GET', '/api/v1/market/tickers', params=params)
        p_symbol = self._symbol_to_pionex(symbol)
        
        if data and 'data' in data and 'tickers' in data['data']:
            for t in data['data']['tickers']:
                if t['symbol'] == p_symbol:
                    return float(t['close'])
        return 0.0

    async def fetch_ticker(self, symbol):
        """ 模拟 CCXT 结构 """
        price = await self.fetch_price(symbol)
        return {
            'symbol': symbol,
            'last': price,
            'close': price,
            'timestamp': int(time.time() * 1000)
        }

    async def fetch_ohlcv(self, symbol, timeframe='15m', limit=100):
        """ 获取 K 线数据 """
        p_symbol = self._symbol_to_pionex(symbol)
        interval = self._map_timeframe(timeframe)
        
        # === [修复开始] 限制 limit 范围 ===
        # Pionex 接口要求 limit 通常在 1-500 之间，超过会报 limit error
        try:
            limit = int(limit)
        except:
            limit = 100
            
        if limit > 500: 
            limit = 500
        if limit < 1: 
            limit = 1
        # === [修复结束] ==================
        
        params = {
            'symbol': p_symbol,
            'interval': interval,
            'limit': limit,
            'type': self.pionex_type
        }
        
        data = await self._request('GET', '/api/v1/market/klines', params=params)
        
        if data and 'data' in data and 'klines' in data['data']:
            ohlcv = []
            for k in data['data']['klines']:
                # Pionex: time, open, high, low, close, volume
                ohlcv.append([
                    int(k['time']),
                    float(k['open']),
                    float(k['high']),
                    float(k['low']),
                    float(k['close']),
                    float(k.get('volume', 0))
                ])
            # 按时间排序
            ohlcv.sort(key=lambda x: x[0])
            return ohlcv
        return []

    async def fetch_symbols(self):
        """ 获取支持的交易对 """
        data = await self._request('GET', '/api/v1/market/tickers')
        symbols = []
        if data and 'data' in data and 'tickers' in data['data']:
            for t in data['data']['tickers']:
                sym = t['symbol']
                # 过滤出 USDT 交易对
                if sym.endswith('_USDT'):
                    symbols.append(self._symbol_from_pionex(sym))
        symbols.sort()
        return symbols

    async def close(self):
        if self.session:
            await self.session.close()

# ================= 补充部分 (必须保留) =================

class BinanceAdapter(ExchangeAdapter):
    """ (保留) Binance 适配器，继续使用 CCXT 逻辑 """
    def __init__(self, exchange_instance):
        super().__init__()
        self.source_name = "binance"
        self.exchange = exchange_instance

    async def fetch_price(self, symbol):
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return float(ticker['last'])
        except:
            return 0.0

    async def fetch_ticker(self, symbol):
        return await self.exchange.fetch_ticker(symbol)

    async def fetch_ohlcv(self, symbol, timeframe, limit=100):
        try:
            return await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        except:
            return []
            
    async def fetch_symbols(self):
        try:
            await self.exchange.load_markets()
            return [s for s in self.exchange.symbols if s.endswith('/USDT')]
        except:
            return []

    async def close(self):
        if self.exchange:
            await self.exchange.close()

class ExchangeFactory:
    """ 工厂类：根据名称创建适配器 """
    @staticmethod
    def create(source_name, ccxt_exchange=None):
        # 注意：Pionex 的创建逻辑已移动到 bot_manager.py 中以注入 Key，这里主要用于兼容
        if source_name == 'pionex':
            return PionexAdapter() 
        elif source_name == 'binance' and ccxt_exchange:
            return BinanceAdapter(ccxt_exchange)
        return None