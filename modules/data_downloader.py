import ccxt.async_support as ccxt
import pandas as pd
import asyncio
import io
from datetime import datetime

async def download_history_kline(symbol, timeframe, start_str, end_str=None, source='binance', proxy_port=0, market_type='spot'):
    """
    从交易所下载历史 K 线并生成 CSV
    start_str: '2023-01-01 00:00:00'
    """
    exchange_class = getattr(ccxt, source)
    
    # [修复] 添加 aiohttp_trust_env: True 以便读取 config.py 设置的系统代理
    args = {
        'enableRateLimit': True,
        'aiohttp_trust_env': True,  # <--- 关键修改：允许自动走系统代理
        'timeout': 30000,            # 建议增加超时时间，防止下载历史数据时超时
        'options': {
            'defaultType': market_type  # 'spot' 或 'future'
        }
    }
    
    # 如果手动指定了端口，依然优先使用手动指定的
    if proxy_port > 0:
        args['proxies'] = {
            'http': f'http://127.0.0.1:{proxy_port}',
            'https': f'http://127.0.0.1:{proxy_port}'
        }
    
    exchange = exchange_class(args)
    
    try:
        # 解析时间
        since = exchange.parse8601(start_str.replace(' ', 'T'))
        if end_str:
            end_ts = exchange.parse8601(end_str.replace(' ', 'T'))
        else:
            end_ts = exchange.milliseconds()
            
        all_ohlcv = []
        
        print(f"📥 开始下载 {symbol} [{timeframe}] 从 {start_str}...")
        
        while since < end_ts:
            # 每次下载 1000 根 (大部分交易所限制)
            try:
                ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since, limit=1000)
            except Exception as e:
                print(f"   ❌ 获取片段失败，重试中... 错误: {e}")
                await asyncio.sleep(2)
                continue

            if not ohlcv:
                break
            
            start_batch = ohlcv[0][0]
            last_batch = ohlcv[-1][0]
            
            # 如果获取到的数据比 since 还早（异常情况），或者没有新数据，退出
            if start_batch < since and len(ohlcv) == 1: 
                break
                
            all_ohlcv.extend(ohlcv)
            print(f"   ...已获取 {len(all_ohlcv)} 根, 最新时间: {exchange.iso8601(last_batch)}")
            
            since = last_batch + 1 # 更新下次起点
            
            # 防止死循环，如果到了终点
            if last_batch >= end_ts:
                break
                
            await asyncio.sleep(exchange.rateLimit / 1000) # 遵守频率限制
            
        await exchange.close()
        
        if not all_ohlcv:
            return None, "no_data_fetched"

        # 转换为 DataFrame
        df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 截取结束时间之前的数据
        df = df[df['timestamp'] <= end_ts]
        
        # 转换为 CSV 字符串
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        return csv_buffer.getvalue(), None

    except Exception as e:
        await exchange.close()
        return None, str(e)