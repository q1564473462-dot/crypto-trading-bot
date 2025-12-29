import aiomysql
import json
import asyncio
from config import DB_CONFIG

class DatabaseManager:
    def __init__(self):
        self.cfg = DB_CONFIG
        self.pool = None

    async def init_pool(self):
        """ 初始化连接池 (必须在异步循环中调用) """
        if self.pool is None:
            self.pool = await aiomysql.create_pool(
                host=self.cfg['host'],
                port=self.cfg['port'],
                user=self.cfg['user'],
                password=self.cfg['password'],
                db=self.cfg['db'],
                charset=self.cfg['charset'],
                cursorclass=aiomysql.DictCursor,
                autocommit=True,
                minsize=5,
                maxsize=100,  # 异步池可以开大一点
            )

    async def close(self):
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    async def get_connection(self):
        if not self.pool:
            await self.init_pool()
        return await self.pool.acquire()

    # --- 用户管理 ---
    async def create_user(self, username, password_hash, language='zh-CN'):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                try:
                    # SQL 插入语句增加 language 字段
                    sql = "INSERT INTO users (username, password_hash, language) VALUES (%s, %s, %s)"
                    await cursor.execute(sql, (username, password_hash, language))
                    return cursor.lastrowid
                except Exception as e:
                    print(f"Create user error: {e}")
                    return None    

    async def get_user_by_username(self, username):
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "SELECT * FROM users WHERE username = %s"
                await cursor.execute(sql, (username,))
                return await cursor.fetchone()

    async def get_user_by_id(self, user_id):
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "SELECT * FROM users WHERE id = %s"
                await cursor.execute(sql, (user_id,))
                return await cursor.fetchone()
            
    # --- [新增] 管理员功能 ---

    async def get_all_users_with_stats(self, search_query=None):
        """ 获取所有用户列表，包含每个用户的机器人数量 """
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = """
                    SELECT 
                        u.id, 
                        u.username, 
                        u.is_admin,
                        u.created_at,
                        u.exchange_source,
                        (SELECT COUNT(*) FROM bots WHERE user_id = u.id) as bot_count,
                        (SELECT SUM(current_profit) FROM bots WHERE user_id = u.id) as total_profit
                    FROM users u
                """
                params = []
                if search_query:
                    sql += " WHERE u.username LIKE %s"
                    params.append(f"%{search_query}%")
                
                sql += " ORDER BY u.id DESC"
                await cursor.execute(sql, params)
                return await cursor.fetchall()
            
    async def update_user_exchange(self, user_id, exchange_source):
        """ [新增] 更新用户的交易所偏好 """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "UPDATE users SET exchange_source = %s WHERE id = %s"
                await cursor.execute(sql, (exchange_source, user_id))

    # --- 机器人管理 ---
    async def create_bot(self, user_id, symbol, strategy_type, initial_config, initial_state, name=None, mode='live'):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                if not name:
                    name = f"{symbol} {strategy_type.upper()}"
                
                # SQL 插入语句增加 mode
                sql = """
                    INSERT INTO bots (user_id, name, symbol, strategy_type, config_json, state_json, total_balance, mode)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                cfg_str = json.dumps(initial_config)
                state_str = json.dumps(initial_state)
                balance = round(float(initial_state.get('balance', 0)), 8)
                # 参数列表增加 mode
                await cursor.execute(sql, (user_id, name, symbol, strategy_type, cfg_str, state_str, balance, mode))
                return cursor.lastrowid

    async def get_all_bots(self, user_id, mode='live'):
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # 增加 WHERE mode = %s
                sql = "SELECT id, name, symbol, strategy_type, is_running, status_msg, current_profit, total_balance, state_json, config_json, folder_id FROM bots WHERE user_id = %s AND mode = %s"
                await cursor.execute(sql, (user_id, mode))
                rows = await cursor.fetchall()
                
                for row in rows:
                    row['state'] = json.loads(row['state_json']) if row.get('state_json') else {}
                    row['config'] = json.loads(row['config_json']) if row.get('config_json') else {}
                    if 'state_json' in row: del row['state_json']
                    if 'config_json' in row: del row['config_json']
                return rows

    async def get_bot_full_data(self, bot_id):
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # [修改] SQL 查询增加了 binance_api_key, binance_api_secret
                sql = """
                    SELECT b.*, u.language, u.exchange_source, 
                           u.api_key, u.api_secret,
                           u.binance_api_key, u.binance_api_secret
                    FROM bots b 
                    JOIN users u ON b.user_id = u.id 
                    WHERE b.id = %s
                """
                await cursor.execute(sql, (bot_id,))
                result = await cursor.fetchone()
                
                if result:
                    result['config'] = json.loads(result['config_json']) if result['config_json'] else {}
                    result['state'] = json.loads(result['state_json']) if result['state_json'] else {}
                    if 'language' not in result or not result['language']:
                        result['language'] = 'zh-CN'
                    
                    if 'exchange_source' not in result or not result['exchange_source']:
                        result['exchange_source'] = 'binance'

                    # === [核心逻辑新增] 根据交易所源，动态映射 Key ===
                    # 这样 bot_manager 只需要读取 result['api_key'] 即可，无需关心是哪个字段来的
                    if result['exchange_source'] == 'binance':
                        result['api_key'] = result.get('binance_api_key')
                        result['api_secret'] = result.get('binance_api_secret')
                    # else: 默认为 pionex，使用原有的 api_key/api_secret 字段
                        
                    if 'config_json' in result: del result['config_json']
                    if 'state_json' in result: del result['state_json']
                return result

    async def update_bot_state(self, bot_id, new_state, status_msg=None, profit=0):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                state_str = json.dumps(new_state)

                balance = round(float(new_state.get('balance', 0)), 8) # [修复] 强制8位精度
                profit = round(float(profit), 8)
                
                if status_msg and len(status_msg) > 250:
                    status_msg = status_msg[:247] + "..."

                if status_msg is None:
                    sql = "UPDATE bots SET state_json = %s, total_balance = %s, current_profit = %s WHERE id = %s"
                    params = [state_str, balance, profit, bot_id]
                else:
                    sql = "UPDATE bots SET state_json = %s, total_balance = %s, current_profit = %s, status_msg = %s WHERE id = %s"
                    params = [state_str, balance, profit, status_msg, bot_id]
                await cursor.execute(sql, params)

    async def update_bot_config(self, bot_id, new_config):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                cfg_str = json.dumps(new_config)
                sql = "UPDATE bots SET config_json = %s WHERE id = %s"
                await cursor.execute(sql, (cfg_str, bot_id))

    async def get_all_running_bots(self):
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "SELECT * FROM bots WHERE is_running = 1"
                await cursor.execute(sql)
                rows = await cursor.fetchall()
                for row in rows:
                    row['config'] = json.loads(row['config_json']) if row['config_json'] else {}
                    row['state'] = json.loads(row['state_json']) if row['state_json'] else {}
                return rows

    async def get_all_bots_for_engine(self):
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # [修改] 同样读取 binance keys
                sql = """
                    SELECT b.*, u.language, u.exchange_source, 
                           u.api_key, u.api_secret,
                           u.binance_api_key, u.binance_api_secret
                    FROM bots b 
                    JOIN users u ON b.user_id = u.id
                """
                await cursor.execute(sql)
                rows = await cursor.fetchall()
                for row in rows:
                    row['config'] = json.loads(row['config_json']) if row['config_json'] else {}
                    row['state'] = json.loads(row['state_json']) if row['state_json'] else {}
                    if not row.get('exchange_source'): row['exchange_source'] = 'binance'
                    
                    # === [核心逻辑新增] ===
                    if row['exchange_source'] == 'binance':
                        row['api_key'] = row.get('binance_api_key')
                        row['api_secret'] = row.get('binance_api_secret')
                    # ====================
                return rows

    async def toggle_bot_status(self, bot_id, is_running, status_msg=None):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # 如果没传 msg，给个默认兜底（防止报错）
                if status_msg is None:
                    status_msg = "🟡 Starting..." if is_running else "🛑 Stopped"
                
                sql = "UPDATE bots SET is_running = %s, status_msg = %s WHERE id = %s"
                val = 1 if is_running else 0
                await cursor.execute(sql, (val, status_msg, bot_id))

    async def delete_bot(self, bot_id):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM trade_logs WHERE bot_id = %s", (bot_id,))
                await cursor.execute("DELETE FROM bots WHERE id = %s", (bot_id,))

    # --- 日志管理 ---

    async def add_log(self, bot_id, action, price, amount, profit=0, fee=0, note=""):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                if note and len(note) > 250: note = note[:247] + "..."

                amount = round(float(amount), 8)
                profit = round(float(profit), 8)
                fee = round(float(fee), 8)

                # SQL 中增加 fee 字段
                sql = """
                    INSERT INTO trade_logs (bot_id, action, price, amount, profit, fee, note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                await cursor.execute(sql, (bot_id, action, price, amount, profit, fee, note))

    async def get_logs(self, bot_id, limit=50):
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "SELECT log_time, action, price, amount, profit, note FROM trade_logs WHERE bot_id = %s ORDER BY log_time DESC LIMIT %s"
                await cursor.execute(sql, (bot_id, limit))
                return await cursor.fetchall()
            
    async def get_bot_rounds(self, bot_id):
        """
        [新增] 获取按回合分组的交易记录
        [优化] 自动计算净利润 (扣除手续费) 并据此判断 win/loss
        """
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "SELECT log_time, action, price, amount, profit, fee, note FROM trade_logs WHERE bot_id = %s ORDER BY id ASC"
                await cursor.execute(sql, (bot_id,))
                logs = await cursor.fetchall()
                
                rounds = []
                current_round_trades = []
                current_round_profit = 0
                current_round_fees = 0  # [新增] 统计本回合手续费
                round_start_time = None
                
                for log in logs:
                    if log.get('log_time'):
                        log['log_time'] = str(log['log_time'])

                    if not current_round_trades:
                        round_start_time = log['log_time']
                    
                    current_round_trades.append(log)
                    
                    p = float(log['profit'] or 0)
                    f = float(log['fee'] or 0) # [新增] 读取手续费
                    current_round_profit += p
                    current_round_fees += f
                    
                    action_str = (log['action'] or "").lower()
                    
                    is_closing = False
                    if p != 0: is_closing = True
                    if 'sell' in action_str or 'close' in action_str or '平仓' in action_str:
                        if p != 0 or 'all' in action_str or 'manual' in action_str:
                            is_closing = True

                    if is_closing:
                        # [关键修改] 计算净利润 = 毛利 - 手续费
                        net_profit = current_round_profit - current_round_fees
                        
                        rounds.append({
                            'round_id': len(rounds) + 1,
                            'start_time': round_start_time,
                            'end_time': log['log_time'],
                            'profit': current_round_profit, # 原始毛利
                            'net_profit': net_profit,       # [新增] 净利润 (用于前端显示)
                            'total_fees': current_round_fees, # [新增] 总手续费
                            'trades': current_round_trades[::-1], 
                            # [关键修改] 胜负判断基于净利润
                            'result': 'win' if net_profit > 0 else ('loss' if net_profit < 0 else 'break_even')
                        })
                        
                        current_round_trades = []
                        current_round_profit = 0
                        current_round_fees = 0
                        round_start_time = None
                
                if current_round_trades:
                    # 进行中的回合也计算一下净浮动 (虽然还没平仓，但开仓手续费已经产生了)
                    net_profit = current_round_profit - current_round_fees
                    rounds.append({
                        'round_id': len(rounds) + 1,
                        'start_time': round_start_time,
                        'end_time': "running",
                        'profit': 0,
                        'net_profit': net_profit,
                        'total_fees': current_round_fees,
                        'trades': current_round_trades[::-1],
                        'result': 'running'
                    })

                return rounds[::-1]
            
    async def get_total_profit(self, bot_id):
        """ 计算指定机器人的累计已实现盈亏 (从日志表求和) """
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # 统计所有利润的总和
                sql = "SELECT SUM(profit) as total FROM trade_logs WHERE bot_id = %s"
                await cursor.execute(sql, (bot_id,))
                result = await cursor.fetchone()
                # 如果没有记录返回 0
                return float(result['total']) if result and result['total'] else 0.0
            
    async def get_total_fees(self, bot_id):
        """ 计算指定机器人的累计手续费 """
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "SELECT SUM(fee) as total FROM trade_logs WHERE bot_id = %s"
                await cursor.execute(sql, (bot_id,))
                result = await cursor.fetchone()
                return float(result['total']) if result and result['total'] else 0.0

    #获取开仓手续费 (用于修正净盈亏计算)
    async def get_buy_fees(self, bot_id):
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # 统计所有开仓动作的手续费
                sql = """
                    SELECT SUM(fee) as total FROM trade_logs 
                    WHERE bot_id = %s 
                    AND (
                        action LIKE '%%Buy%%' OR 
                        action LIKE '%%买入%%' OR 
                        action LIKE '%%补仓%%' OR
                        action LIKE '%%首单%%' OR
                        action LIKE '%%Base%%'
                    )
                """
                await cursor.execute(sql, (bot_id,))
                result = await cursor.fetchone()
                return float(result['total']) if result and result['total'] else 0.0

    # 在 modules/database.py 的用户管理区域添加
    async def update_user_language(self, user_id, lang_code):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE users SET language = %s WHERE id = %s", (lang_code, user_id))

    # --- 文件夹管理 ---

    async def create_folder(self, user_id, name):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "INSERT INTO folders (user_id, name) VALUES (%s, %s)"
                await cursor.execute(sql, (user_id, name))
                return cursor.lastrowid

    async def get_user_folders(self, user_id):
        if not self.pool: await self.init_pool()
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sql = "SELECT * FROM folders WHERE user_id = %s ORDER BY id ASC"
                await cursor.execute(sql, (user_id,))
                return await cursor.fetchall()

    async def delete_folder(self, user_id, folder_id):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # 1. 先把该文件夹下的机器人 folder_id 置空
                await cursor.execute("UPDATE bots SET folder_id = NULL WHERE folder_id = %s AND user_id = %s", (folder_id, user_id))
                # 2. 删除文件夹
                await cursor.execute("DELETE FROM folders WHERE id = %s AND user_id = %s", (folder_id, user_id))

    async def update_bot_folder(self, user_id, bot_id, folder_id):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # folder_id 为 None 代表移出文件夹
                sql = "UPDATE bots SET folder_id = %s WHERE id = %s AND user_id = %s"
                await cursor.execute(sql, (folder_id, bot_id, user_id))

    async def update_user_api_keys(self, user_id, api_key, api_secret):
        """ 
        [修正] 智能更新 API Key 
        根据用户当前的 exchange_source 判断 Key 应该存入通用字段还是币安专用字段
        """
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # 1. 先查询用户当前的交易所偏好
                await cursor.execute("SELECT exchange_source FROM users WHERE id = %s", (user_id,))
                row = await cursor.fetchone()
                source = row['exchange_source'] if row else 'pionex'
                
                # 2. 根据交易所源，写入不同的列
                if source == 'binance':
                    sql = "UPDATE users SET binance_api_key = %s, binance_api_secret = %s WHERE id = %s"
                else:
                    # 默认 (Pionex) 使用通用字段
                    sql = "UPDATE users SET api_key = %s, api_secret = %s WHERE id = %s"
                
                await cursor.execute(sql, (api_key, api_secret, user_id))

db = DatabaseManager()