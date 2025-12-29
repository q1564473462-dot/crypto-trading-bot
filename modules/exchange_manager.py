import time
import asyncio
import ccxt.pro as ccxt
from modules.adapters import ExchangeFactory, PionexAdapter, BinanceAdapter
from modules.globals import WS_PRICE_CACHE, EXCHANGE_CACHE

# ================= WebSocket 管理器 =================

class StreamManager:
    def __init__(self):
        self.exchange = None
        self.running = False
        self.active_symbols = set()
        self.task = None
        self.current_source = 'binance'

    async def start(self, source='binance'):
        if self.running and self.exchange and self.current_source == source:
            return
        
        if self.running:
            await self.stop()
        
        self.running = True
        self.current_source = source
        print(f">>> 🔌 正在启动 WebSocket 数据流 ({source})...")
        try:
            exchange_class = getattr(ccxt, source, None)
            if not exchange_class:
                print(f"WS Error: Unsupported exchange {source}")
                self.running = False
                return
            options = {
                'enableRateLimit': True,
                'aiohttp_trust_env': True,
            }

            if source == 'binance':
                options['options'] = { 'defaultType': 'future' }

            self.exchange = exchange_class(options)
            
            self.task = asyncio.create_task(self._loop())
        except Exception as e:
            print(f"WS Start Error ({source}): {e}")
            self.running = False

    async def stop(self):
        self.running = False
        print(">>> 🔌 正在停止 WebSocket 数据流...")
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"WS Task Close Error: {e}")
        
        if self.exchange:
            try:
                await self.exchange.close()
                print(">>> ✅ WebSocket Exchange Closed.")
            except Exception as e:
                print(f"WS Exchange Close Error: {e}")
            finally:
                self.exchange = None
                WS_PRICE_CACHE.clear()

    def update_symbols(self, symbols):
        self.active_symbols = set(symbols)

    async def _loop(self):
        while self.running:
            try:
                if not self.active_symbols:
                    await asyncio.sleep(1)
                    continue
                symbols = list(self.active_symbols)
                tickers = await self.exchange.watch_tickers(symbols)
                for symbol, ticker in tickers.items():
                    WS_PRICE_CACHE[symbol] = {'price': ticker['last'], 'ts': time.time()}
            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(5)

stream_manager = StreamManager()

# ================= 交易所连接管理 =================

def get_cached_exchange(bot_config):
    exchange_source = bot_config.get('exchange_source', 'binance')
    market_type = bot_config.get('market_type', 'future')
    user_id = bot_config.get('user_id') 
    raw_key = bot_config.get('api_key')
    raw_secret = bot_config.get('api_secret')
    
    api_key = str(raw_key).strip() if raw_key else None
    api_secret = str(raw_secret).strip() if raw_secret else None

    if api_key in ['None', '', 'null']: api_key = None
    if api_secret in ['None', '', 'null']: api_secret = None

    if bot_config.get('paper_trading', False):
        api_key = None
        api_secret = None

    if not user_id:
        print("⚠️ Error: Missing user_id in exchange init")
        return None

    cache_key = f"{user_id}_{exchange_source}_{market_type}"
    if cache_key in EXCHANGE_CACHE:
        return EXCHANGE_CACHE[cache_key]
    
    # print(f">>> 🆕 初始化交易所: User {user_id} -> {exchange_source}")
    adapter = None

    try:
        if exchange_source == 'pionex':
            adapter = PionexAdapter(api_key, api_secret, market_type)
        elif exchange_source == 'binance':
            if not hasattr(ccxt, exchange_source): return None
            exchange_class = getattr(ccxt, exchange_source)
            options = {
                'timeout': 10000, 
                'enableRateLimit': True,
                'aiohttp_trust_env': True,
                'options': { 'defaultType': 'spot' if market_type == 'spot' else 'future' }
            }
            if api_key and api_secret:
                options['apiKey'] = api_key
                options['secret'] = api_secret
                
            ccxt_instance = exchange_class(options)
            adapter = ExchangeFactory.create(exchange_source, ccxt_instance)
            if not adapter: adapter = ccxt_instance

        if adapter:
            EXCHANGE_CACHE[cache_key] = adapter
            return adapter

    except Exception as e:
        print(f"Failed to create exchange {cache_key}: {e}")
        return None

async def close_all_exchanges():
    print("\n>>> 🧹 开始清理交易所连接...")
    try:
        await stream_manager.stop()
    except Exception as e:
        print(f"Error closing StreamManager: {e}")

    for key, ex in EXCHANGE_CACHE.items():
        try:
            await ex.close()
        except Exception as e:
            print(f">>> ❌ Error closing {key}: {e}")
    EXCHANGE_CACHE.clear()

async def clear_user_exchange_cache(user_id):
    if not user_id: return
    print(f">>> ♻️ 正在为用户 {user_id} 清理旧交易所连接...")
    keys_to_delete = [k for k in EXCHANGE_CACHE.keys() if str(k).startswith(f"{user_id}_")]
    for key in keys_to_delete:
        adapter = EXCHANGE_CACHE.get(key)
        if adapter:
            try:
                await adapter.close()
            except Exception: pass
        EXCHANGE_CACHE.pop(key, None)

async def fetch_exchange_symbols(source='binance'):
    temp_adapter = None
    try:
        if source == 'pionex':
            temp_adapter = PionexAdapter()
        else:
            import ccxt.pro as ccxt
            options = {
                'timeout': 10000, 
                'enableRateLimit': True,
                'aiohttp_trust_env': True,  # 关键：允许读取系统代理设置
                'options': { 'defaultType': 'future' }
            }
            raw_ex = ccxt.binance(options)
            temp_adapter = BinanceAdapter(raw_ex)
        return await temp_adapter.fetch_symbols()
    except Exception as e:
        print(f"Fetch Symbols Error: {e}")
        return []
    finally:
        if temp_adapter: await temp_adapter.close()

async def fetch_symbol_info(symbol, market_type='future', source='binance', api_key=None, api_secret=None):
    temp_ex = None
    try:
        # 目前只针对币安进行自动获取，Pionex 逻辑暂缺
        if source != 'binance':
            return None

        import ccxt.pro as ccxt
        options = {
            'timeout': 10000, 
            'enableRateLimit': True,
            'aiohttp_trust_env': True,
            'options': { 'defaultType': 'spot' if market_type == 'spot' else 'future' }
        }
        
        if api_key and api_secret:
            options['apiKey'] = api_key
            options['secret'] = api_secret
            
        exchange_class = getattr(ccxt, source)
        temp_ex = exchange_class(options)
        
        # 加载市场信息
        await temp_ex.load_markets()
        
        if symbol in temp_ex.markets:
            market = temp_ex.markets[symbol]
            
            # 1. 获取数量精度 (Step Size)
            # CCXT 结构通常是 market['precision']['amount']
            # 对于 Binance，这通常就是 stepSize (如 0.001)
            precision = market.get('precision', {}).get('amount', 0.001)
            
            # 2. 获取手续费率 (Fee Rate)
            # 优先获取 taker 费率
            fee_rate = 0.0005 # 默认万5
            if market.get('taker') is not None:
                fee_rate = float(market['taker'])
            elif market.get('feeSide') == 'get': # 有些交易所结构不同
                pass 
                
            # 如果没获取到具体费率，尝试 fetch_trading_fees (需要权限)
            # 但为了速度，通常 load_markets 里的 info 就够了
            
            print(f">>> 🔍 自动获取 {symbol} ({market_type}) 信息: Precision={precision}, Fee={fee_rate}")
            return {
                'precision': precision,
                'fee_rate': fee_rate
            }
        else:
            print(f">>> ⚠️ 自动获取失败: 交易对 {symbol} 不存在于 {market_type}")
            return None

    except Exception as e:
        print(f">>> ⚠️ 获取币种信息异常: {e}")
        return None
    finally:
        if temp_ex:
            await temp_ex.close()