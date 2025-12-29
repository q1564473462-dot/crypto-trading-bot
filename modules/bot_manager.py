import asyncio
from modules.database import db

# ================= 导入各子模块功能 =================

# 1. 从 Globals 导入
from modules.globals import (
    RUNTIME_CACHE, WS_PRICE_CACHE, BOT_LOCKS, 
    get_bot_lock, adjust_precision
)

# 2. 从 Exchange Manager 导入
from modules.exchange_manager import (
    stream_manager, get_cached_exchange, close_all_exchanges, 
    clear_user_exchange_cache, fetch_exchange_symbols
)

# 3. 从 Manual Ops 导入
from modules.manual_ops import execute_manual_buy, execute_manual_close

# 4. 从 Bot Logic 导入
from modules.bot_logic import run_bot_logic

# 5. 特殊补充函数 (因为需要 db，放在这里或独立的 data_fetcher)
async def get_bot_kline(bot_id, timeframe='15m', limit=100):
    bot_data = await db.get_bot_full_data(bot_id)
    if not bot_data: return []
    cfg = bot_data.get('config', {})
    
    # 补全必要认证信息
    cfg.update({
        'user_id': bot_data.get('user_id'),
        'api_key': bot_data.get('api_key'),
        'api_secret': bot_data.get('api_secret'),
        'exchange_source': bot_data.get('exchange_source', 'binance')
    })
    
    symbol = bot_data.get('symbol') or cfg.get('symbol')
    if not symbol: return []

    exchange = get_cached_exchange(cfg)
    if not exchange: return []
    
    try:
        limit = int(limit)
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        return [{'time': int(c[0]/1000), 'open': c[1], 'high': c[2], 'low': c[3], 'close': c[4]} for c in ohlcv]
    except Exception as e:
        print(f"Kline Fetch Error: {e}")
        return []

# ================= 主引擎循环 =================

async def bot_engine_loop():
    print(">>> 启动高性能 Async 策略引擎 (Modularized)...")
    await db.init_pool() 
    
    # 启动 WebSocket
    await stream_manager.start(source='binance')
    
    while True:
        try:
            all_bots = await db.get_all_bots_for_engine()
            
            if all_bots:
                # 动态管理 WebSocket 订阅
                target_symbols = set()
                current_ws_source = stream_manager.current_source
                
                for bot in all_bots:
                    bot_source = bot.get('exchange_source', 'binance')
                    if bot.get('symbol') and bot_source == current_ws_source:
                        target_symbols.add(bot['symbol'])
                
                stream_manager.update_symbols(target_symbols)
                
                # 并发执行所有机器人逻辑
                tasks = []
                for bot in all_bots:
                    task = asyncio.wait_for(run_bot_logic(bot), timeout=8.0)
                    tasks.append(task)
                
                # 等待执行结果
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for i, res in enumerate(results):
                    if isinstance(res, Exception) and not isinstance(res, asyncio.TimeoutError):
                        print(f"❌ Bot {all_bots[i]['id']} Error: {res}")
            else:
                stream_manager.update_symbols(set())
                await asyncio.sleep(2)
            
            await asyncio.sleep(1)
        except Exception as e:
            print(f"Engine Loop Error: {e}")
            await asyncio.sleep(5)