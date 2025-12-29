from quart import Blueprint, request, jsonify, session
from languages import TRANSLATIONS
from modules.database import db
from modules.manual_ops import execute_manual_buy, execute_manual_close
from modules.bot_manager import (
    RUNTIME_CACHE, get_bot_kline, get_bot_lock, 
    fetch_exchange_symbols, clear_user_exchange_cache
)
from utils import get_t, get_current_user, login_required, check_bot_ownership
from modules.backtest_engine import run_backtest
from modules.data_downloader import download_history_kline
from quart import Response
from datetime import datetime
from modules.exchange_manager import fetch_symbol_info

# 定义蓝图
api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/add_bot', methods=['POST'])
@login_required
async def add_bot():
    user = await get_current_user()
    form = await request.form

    mode = form.get('mode', 'live')
    
    # 获取前端提交的参数
    symbol = form.get('symbol', 'BTC/USDT')
    capital = float(form.get('capital', 1000))
    s_type = form.get('strategy_type', 'fvg') 
    name = form.get('name', '').strip()

    market_type = form.get('market_type', 'future')

    exch_source = user.get('exchange_source', 'binance')
    api_key = user.get('binance_api_key') if exch_source == 'binance' else user.get('api_key')
    api_secret = user.get('binance_api_secret') if exch_source == 'binance' else user.get('api_secret')

    fetched_info = await fetch_symbol_info(symbol, market_type, exch_source, api_key, api_secret)

    precision = 0.001
    fee = 0.0005
    if fetched_info:
        precision = fetched_info['precision']
        fee = fetched_info['fee_rate']
    
    # 1. 基础通用配置
    default_config = {
        "symbol": symbol,
        "capital": capital,
        "leverage": 1,                
        "proxy_port": 0,              # [修改] 默认保留字段为0，但不从前端获取
        "market_type": market_type,      
        "fee_rate": fee,           
        "amount_precision": precision,  
        "manual_close_action": "stop" 
    }
    
    default_state = {}
    
    if s_type == 'grid_dca':
        # --- Auto Grid DCA ---
        default_config.update({
            "grid_count": 10,
            "range_percent": 0.20,
            "tp_target": 1.5,
            "grid_type": "arithmetic",
            "direction": "long",
            "stop_loss_percent": 15.0, # 默认不开启止损
            "cooldown_seconds": 60,    # 默认冷却 60秒
            "trailing_dev": 0.2,
        })
        default_state = {
            "balance": capital,
            "position_amt": 0.0,
            "total_cost": 0.0,
            "avg_price": 0.0,
            "range_top": 0.0,
            "range_bottom": 0.0,
            "last_level_idx": 10, 
        }
        
    elif s_type == 'coffin':
        # --- Coffin ---
        default_config.update({
            "direction": "long",
            "coffin_lookback": 3,
            "be_trigger": 0.5,
            "trailing_gap": 1.0,
            "retest_tolerance": 0.1,
            "cooldown_seconds": 60
        })
        default_state = {
            "balance": capital,
            "position_amt": 0.0,
            "total_cost": 0.0,
            "avg_price": 0.0,
            "stage": "IDLE",
            "stop_loss_price": 0.0,
            "extreme_price": 0.0
        }

    elif s_type == 'periodic':
        # --- [新增] Periodic 定投 ---
        default_config.update({
            "direction": "long",
            "interval_minutes": 60, # 默认60分钟
            "invest_amount": 10,  # 默认每次10U
            "price_limit": 0,     # 默认无限制
            "leverage": 1,        # 默认1倍
            "cooldown_seconds": 5 # 定投不需要太长的冷却，防止重复触发即可
        })
        default_state = {
            "balance": capital,
            "position_amt": 0.0,
            "total_cost": 0.0,
            "avg_price": 0.0,
            "last_invest_time": 0, # 上次定投时间
            "direction": "long"
        }

    else:
        # --- 默认: FVG DCA ---
        default_config.update({
            "direction": "long",
            "max_orders": 7,
            "volume_scale": 1.3,
            "step_percent": 1.0,
            "step_scale": 1.2,
            "tp_target": 1.2,
            "stop_loss_percent": 15.0,
            "trailing_dev": 0.2,
            "use_fvg": True,
            "fvg_timeframes": "15m,1h,4h",
            "cooldown_seconds": 60
        })
        default_state = {
            "balance": capital,
            "position_amt": 0.0,
            "direction": "long",
            "avg_price": 0.0,
            "total_cost": 0.0,
            "initial_base_price": 0.0,
            "current_so_index": 1,
            "lowest_price_seen": 0.0,
            "highest_price_seen": 0.0,
            "is_trailing_active": False,
            "next_trade_time": 0
        }
    
    try:
        await db.create_bot(user['id'], symbol, s_type, default_config, default_state, name=name, mode=mode)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@api_bp.route('/delete_bot', methods=['POST'])
@login_required
async def delete_bot_route():
    t = get_t()
    form = await request.form
    bot_id = form.get('bot_id')
    if not bot_id: return jsonify({"status": "error", "msg": "No ID"})
    bot_id = int(bot_id)

    bot_data = await check_bot_ownership(bot_id)
    if bot_data is False: return jsonify({"status": "error", "msg": t("flash_unauthorized_action")})
    if bot_data is None: return jsonify({"status": "error", "msg": t("instance_not_found")})
    
    state = bot_data.get('state', {})
    pos_amt = float(state.get('position_amt', 0))
    
    if abs(pos_amt) > 0:
        return jsonify({"status": "error", "msg": f"❌ {t('delete_rejected_due_to_open_position')}: {pos_amt}！\n{t('please_close_position_first')}。"})
    if bot_data.get('is_running', 0) == 1:
            return jsonify({"status": "error", "msg": f"❌ {t('delete_rejected_due_to_running_bot')}！\n{t('please_stop_running_first')}。"})

    await db.delete_bot(bot_id)
    return jsonify({"status": "success"})

@api_bp.route('/get_dashboard_stats')
@login_required
async def get_dashboard_stats():
    user = await get_current_user()
    
    # [新增] 从请求中获取 mode
    mode = request.args.get('mode', 'live')
    
    # 只获取对应模式的机器人
    bots = await db.get_all_bots(user['id'], mode=mode)
    data = []
    
    for bot in bots:
        # 1. 获取基础数据
        state = bot.get('state', {})
        cfg = bot.get('config', {})
        bot_id = bot['id']
        strategy_type = bot.get('strategy_type', 'fvg')
        
        pos_amt = float(state.get('position_amt', 0))
        avg_price = float(state.get('avg_price', 0))
        total_cost = float(state.get('total_cost', 0)) 
        realized_profit = float(bot['current_profit'] or 0)
        
        # 2. 获取实时价格
        realtime = RUNTIME_CACHE.get(bot_id, {})
        market_price = realtime.get('market_price', 0)
        
        # 3. 计算浮动盈亏与回撤
        floating_pnl = 0.0
        drawdown_pct = 0.0
        
        if abs(pos_amt) > 0 and market_price > 0 and avg_price > 0:
            direction = state.get('direction', cfg.get('direction', 'long'))
            if direction == 'short':
                floating_pnl = (avg_price - market_price) * abs(pos_amt)
                drawdown_pct = (market_price - avg_price) / avg_price * 100
            else:
                floating_pnl = (market_price - avg_price) * abs(pos_amt)
                drawdown_pct = (avg_price - market_price) / avg_price * 100

        # 4. 计算净盈亏
        net_pnl = realized_profit + floating_pnl
        direction_display = state.get('direction', cfg.get('direction', 'long')).upper()
        
        # [新增] 提取杠杆
        leverage = float(cfg.get('leverage', 1))

        # 5. 提取策略特定数据 (扩充版)
        strat_info = {}
        strat_info['stage'] = state.get('stage', 'IDLE') # Coffin 专用

        if strategy_type == 'grid_dca':
            strat_info['grid_anchor'] = state.get('last_level_idx', -1)
            strat_info['is_trailing'] = state.get('is_trailing_active', False)
            # 提取极值
            if direction_display == 'LONG':
                strat_info['extreme'] = float(state.get('highest_price_seen', 0))
            else:
                strat_info['extreme'] = float(state.get('lowest_price_seen', 0))

        elif strategy_type == 'coffin':
            strat_info['sl'] = float(state.get('stop_loss_price', 0))
            strat_info['extreme'] = float(state.get('extreme_price', 0))
            # 提取箱体
            box = state.get('coffin_5m', {})
            if box and 'top' in box and 'bottom' in box:
                strat_info['box_5m'] = f"${box['bottom']:.2f} - ${box['top']:.2f}"
            else:
                strat_info['box_5m'] = "---"
        
        else: # FVG
            strat_info['is_trailing'] = state.get('is_trailing_active', False)
            if direction_display == 'LONG':
                strat_info['extreme'] = float(state.get('highest_price_seen', 0))
            else:
                strat_info['extreme'] = float(state.get('lowest_price_seen', 0))

        data.append({
            'id': bot_id,
            'name': bot.get('name') or bot['symbol'], 
            'symbol': bot.get('symbol'), # 确保有 symbol
            'strategy_type': strategy_type,
            'current_profit': realized_profit,
            'total_balance': float(bot['total_balance'] or 0),
            'is_running': int(bot['is_running']),
            'status_msg': bot['status_msg'] or '',
            'pos_amt': pos_amt,
            'avg_price': avg_price,
            'total_cost': total_cost,
            'floating_pnl': floating_pnl,
            'drawdown_pct': drawdown_pct,
            'direction': direction_display,
            'net_pnl': net_pnl,
            'strat_info': strat_info,
            'market_price': market_price, # [新增] 传递市价
            'leverage': leverage,         # [新增] 传递杠杆
            'folder_id': bot.get('folder_id')
        })
        
    return jsonify(data)

@api_bp.route('/get_data/<int:bot_id>')
@login_required
async def get_data(bot_id):
    bot_data = await check_bot_ownership(bot_id)
    if bot_data is False: return jsonify({"error": "Unauthorized"}), 403
    if bot_data is None: return jsonify({"error": "Bot not found"}), 404
    
    realtime = RUNTIME_CACHE.get(bot_id, {})
    market_price = realtime.get('market_price', 0.0)
    ladder = realtime.get('ladder', [])
    state = bot_data['state']
    cfg = bot_data['config']
    
    pnl = 0
    pnl_pct = 0
    drawdown = 0
    
    if float(state.get('position_amt', 0)) != 0 and market_price > 0:
        avg = float(state.get('avg_price', 0))
        pos = float(state.get('position_amt', 0))
        cost = float(state.get('total_cost', 0))
        
        val_now = pos * market_price
        direction = state.get('direction', cfg.get('direction', 'long'))
        
        entry_val = pos * avg
        if direction == 'short':
            pnl = entry_val - val_now
            if avg > 0: drawdown = -((market_price - avg) / avg * 100)
        else:
             pnl = val_now - entry_val
             if avg > 0: drawdown = (market_price - avg) / avg * 100
             
        if cost > 0: pnl_pct = (pnl / cost) * 100

    logs = await db.get_logs(bot_id, limit=50)
    log_strs = []
    for row in logs:
        ts = row['log_time']
        if not isinstance(ts, str): ts = str(ts)
        msg = f"[{ts}] {row['action']}: ${float(row['price'] or 0):.2f} | {row['note'] or ''}"
        log_strs.append(msg)

    rounds = await db.get_bot_rounds(bot_id)

    # 1. 获取数据库存的“不完全净值” (扣除了卖出费，没扣买入费)
    db_realized_profit = await db.get_total_profit(bot_id)
    
    # 2. 获取手续费明细
    total_fees = await db.get_total_fees(bot_id)
    buy_fees = await db.get_buy_fees(bot_id)
    
    # 3. 推算卖出费 (总费 - 买入费)
    sell_fees = total_fees - buy_fees
    
    # 4. 计算核心指标
    # [毛利 Gross] = 数据库存的利润 + 卖出费 (把扣掉的加回来，还原成纯K线价差)
    gross_profit = db_realized_profit + sell_fees
    
    # [真·净盈亏 Net] = 数据库存的利润 - 买入费 (把没扣的扣掉)
    # 加上 pnl (浮动盈亏) 就是此时此刻的总净值变动
    net_pnl = db_realized_profit - buy_fees + pnl

    response = {
        "config": cfg,
        "state": state,
        "mode": bot_data.get('mode', 'live'),
        "strategy_type": bot_data.get('strategy_type', 'fvg'),
        "name": bot_data.get('name') or cfg.get('symbol'),
        "global": {
            "is_running": bool(bot_data['is_running']),
            "status_msg": bot_data['status_msg'],
            "market_price": market_price, 
            "logs": log_strs,
            "ladder_preview": ladder,
            "rounds": rounds
        },
        "metrics": {
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "drawdown": drawdown,
            "net_pnl": net_pnl,
            "total_fees": total_fees,
            "daily_stats": {"profit": gross_profit} 
        }
    }
    return jsonify(response)

@api_bp.route('/update_config', methods=['POST'])
@login_required
async def update_config():
    t = get_t()
    data = await request.json
    bot_id = data.get('bot_id')
    new_cfg = data.get('config')
    if not bot_id: return jsonify({"status": "error", "msg": "No ID"})
    
    lock = get_bot_lock(bot_id)
    async with lock:
        bot_data = await check_bot_ownership(bot_id)
        if bot_data is False: return jsonify({"status": "error", "msg": t("flash_unauthorized_action")})

        try:
            old_cfg = bot_data['config']
            state = bot_data['state']

            strategy_type = bot_data.get('strategy_type', 'fvg')
            
            # --- 1. 安全检查 ---
            direction_changed = False
            if 'direction' in new_cfg and new_cfg['direction'] != old_cfg.get('direction'):
                direction_changed = True

            if direction_changed:
                pos_amt = float(state.get('position_amt', 0))
                if abs(pos_amt) > 0:
                    return jsonify({
                        "status": "error", 
                        "msg": f"❌ {t('dangerous_operation_intercepted')}\n\n{t('current_position')}: {pos_amt}，{t('direction_change_forbidden')}。\n{t('please_manual_close_first')}"
                    })
                
            if 'leverage' in new_cfg and float(new_cfg['leverage']) != float(old_cfg.get('leverage', 1)):
                pos_amt = float(state.get('position_amt', 0))
                if abs(pos_amt) > 0:
                    return jsonify({
                        "status": "error", 
                        "msg": f"❌ {t('dangerous_operation_intercepted')}\n\n{t('current_position')}: {pos_amt}，禁止修改杠杆。\n{t('please_manual_close_first')}"
                    })
                
            need_fetch = False
            target_symbol = new_cfg.get('symbol', old_cfg.get('symbol'))
            target_market = new_cfg.get('market_type', old_cfg.get('market_type'))

            if 'symbol' in new_cfg and new_cfg['symbol'] != old_cfg.get('symbol'):
                need_fetch = True
            if 'market_type' in new_cfg and new_cfg['market_type'] != old_cfg.get('market_type'):
                need_fetch = True

            if need_fetch:
                # bot_data 已经包含用户的 API Key (通过 get_bot_full_data 联合查询)
                exch_source = bot_data.get('exchange_source', 'binance')
                ak = bot_data.get('api_key')
                sk = bot_data.get('api_secret')
                
                fetched = await fetch_symbol_info(target_symbol, target_market, exch_source, ak, sk)
                if fetched:
                    # 将获取到的新值写入 new_cfg，稍后会被 update 到 final_cfg
                    new_cfg['amount_precision'] = fetched['precision']
                    new_cfg['fee_rate'] = fetched['fee_rate']

            # --- 2. 数据类型转换 (删除了 proxy_port 的处理) ---
            if 'fee_rate' in new_cfg: new_cfg['fee_rate'] = float(new_cfg['fee_rate'])

            if 'order_amount' in new_cfg: 
                new_cfg['order_amount'] = float(new_cfg['order_amount'])
            if 'leverage' in new_cfg: 
                lev = float(new_cfg['leverage'])
                if lev < 1:
                    return jsonify({"status": "error", "msg": f"❌ {t('save_failed')}: {t('leverage_must_be_gte_1')}"})
                new_cfg['leverage'] = lev
            if 'amount_precision' in new_cfg: new_cfg['amount_precision'] = float(new_cfg['amount_precision'])
            
            if 'max_orders' in new_cfg: new_cfg['max_orders'] = int(new_cfg['max_orders'])
            if 'volume_scale' in new_cfg: new_cfg['volume_scale'] = float(new_cfg['volume_scale'])
            if 'step_percent' in new_cfg: new_cfg['step_percent'] = float(new_cfg['step_percent'])
            if 'step_scale' in new_cfg: new_cfg['step_scale'] = float(new_cfg['step_scale'])
            if 'stop_loss_percent' in new_cfg: new_cfg['stop_loss_percent'] = float(new_cfg['stop_loss_percent'])
            
            if 'tp_target' in new_cfg: new_cfg['tp_target'] = float(new_cfg['tp_target'])

            if 'stop_loss_percent' in new_cfg: new_cfg['stop_loss_percent'] = float(new_cfg['stop_loss_percent'])
            
            if 'cooldown_seconds' in new_cfg:
                cd = int(new_cfg['cooldown_seconds'])
                if cd < 0: cd = 60
                new_cfg['cooldown_seconds'] = cd

            if 'trailing_dev' in new_cfg: new_cfg['trailing_dev'] = float(new_cfg['trailing_dev'])

            if 'cooldown_seconds' in new_cfg:
                cd = int(new_cfg['cooldown_seconds'])
                if cd < 0: cd = 60
                new_cfg['cooldown_seconds'] = cd
            
            if 'be_trigger' in new_cfg: new_cfg['be_trigger'] = float(new_cfg['be_trigger'])
            if 'trailing_gap' in new_cfg: new_cfg['trailing_gap'] = float(new_cfg['trailing_gap'])
            if 'retest_tolerance' in new_cfg: new_cfg['retest_tolerance'] = float(new_cfg['retest_tolerance'])

            if 'cooldown_seconds' in new_cfg:
                cd = int(new_cfg['cooldown_seconds'])
                if cd < 0: cd = 60 # 负数强制回正
                new_cfg['cooldown_seconds'] = cd

            if 'range_top' in new_cfg: new_cfg['range_top'] = float(new_cfg['range_top'])
            if 'range_bottom' in new_cfg: new_cfg['range_bottom'] = float(new_cfg['range_bottom'])
            if 'range_percent' in new_cfg: new_cfg['range_percent'] = float(new_cfg['range_percent'])
            if 'grid_count' in new_cfg: new_cfg['grid_count'] = int(new_cfg['grid_count'])

            if 'interval_minutes' in new_cfg: new_cfg['interval_minutes'] = float(new_cfg['interval_minutes'])
            if 'invest_amount' in new_cfg: new_cfg['invest_amount'] = float(new_cfg['invest_amount'])
            if 'price_limit' in new_cfg: new_cfg['price_limit'] = float(new_cfg['price_limit'])

            if strategy_type == 'periodic' and 'leverage' in new_cfg:
                if float(new_cfg['leverage']) > 3: new_cfg['leverage'] = 3

            final_cfg = old_cfg.copy()
            final_cfg.update(new_cfg)

            if final_cfg.get('market_type') == 'spot':
                final_cfg['leverage'] = 1.0
                new_cfg['leverage'] = 1.0
            
            await db.update_bot_config(bot_id, final_cfg)
            
            # --- 3. 处理策略重置 ---
            reset_needed = False
            reset_msg = ""

            if direction_changed:
                reset_needed = True
                reset_msg = t("direction_changed_bot_reset")
                state['next_trade_time'] = 0
                
                if strategy_type == 'grid_dca':
                    state['range_top'] = 0.0
                    state['range_bottom'] = 0.0
                    state['last_level_idx'] = -1
                elif strategy_type == 'fvg':
                    state['current_so_index'] = 1
                    state['initial_base_price'] = 0.0
                    state['highest_price_seen'] = 0.0
                    state['lowest_price_seen'] = 0.0
                    state['is_trailing_active'] = False
                elif strategy_type == 'fib_grid':
                    state['last_level_idx'] = -1
                    state['range_top'] = 0.0
                    state['range_bottom'] = 0.0
                elif strategy_type == 'coffin':
                    state['stage'] = 'IDLE'
                    state['stop_loss_price'] = 0.0
                    state['extreme_price'] = 0.0

            elif strategy_type == 'fib_grid': 
                old_rp = old_cfg.get('range_percent', 0)
                new_rp = new_cfg.get('range_percent', 0)
                if new_rp != old_rp:
                    state['range_top'] = 0.0
                    state['range_bottom'] = 0.0
                    state['last_level_idx'] = -1
                    reset_needed = True
                    reset_msg = f"Range% {t('changed_bot_reset')}"

                if ('range_top' in new_cfg and new_cfg['range_top'] != old_cfg.get('range_top')) or \
                   ('range_bottom' in new_cfg and new_cfg['range_bottom'] != old_cfg.get('range_bottom')):
                    state['last_level_idx'] = -1
                    reset_needed = True
                    reset_msg = t("range_changed_anchor_reset")

            if reset_needed:
                current_profit = float(bot_data.get('current_profit', 0))
                await db.update_bot_state(bot_id, state, reset_msg, current_profit)
            
            if bot_id in RUNTIME_CACHE:
                RUNTIME_CACHE[bot_id]['last_fvg_update_time'] = 0

            return jsonify({"status": "success", "msg": t("config_saved") + (" (" + t("status_reset") + ")" if reset_needed else "")})

        except Exception as e:
            return jsonify({"status": "error", "msg": str(e)})

@api_bp.route('/toggle_bot', methods=['POST'])
@login_required
async def toggle_bot():
    t = get_t()
    data = await request.json
    bot_id = data.get('bot_id')
    action = data.get('action')
    
    lock = get_bot_lock(bot_id)
    async with lock:
        if await check_bot_ownership(bot_id) is False: 
            return jsonify({"status": "error", "msg": t("flash_unauthorized_action")})
        
        # [修改] 根据当前语言生成状态文字
        is_start = (action == 'start')
        status_text = t('status_starting') if is_start else t('status_stopped')
        
        # [修改] 将翻译好的文字传给数据库
        await db.toggle_bot_status(bot_id, is_start, status_text)
        
        return jsonify({"status": "success"})
@api_bp.route('/manual_buy', methods=['POST'])
@login_required
async def manual_buy_route():
    t = get_t()
    data = await request.json
    bot_id = data.get('bot_id')
    if await check_bot_ownership(bot_id) is False: 
        return jsonify({"status": "error", "msg": t("flash_unauthorized_action")})
        
    try:
        amount_usd = float(data.get('amount', 0))
        if amount_usd <= 0: raise ValueError(t("amount_must_be_positive"))
        await execute_manual_buy(bot_id, amount_usd)
        return jsonify({"status": "success", "msg": f"✅ {t('manual_buy_success')}"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@api_bp.route('/manual_close', methods=['POST'])
@login_required
async def manual_close_route():
    t = get_t()
    data = await request.json
    bot_id = data.get('bot_id')
    if await check_bot_ownership(bot_id) is False: 
        return jsonify({"status": "error", "msg": t("flash_unauthorized_action")})
        
    try:
        profit = await execute_manual_close(bot_id)

        sign = "+" if profit >= 0 else ""
        return jsonify({"status": "success", "msg": f"✅ {t('manual_close_success')}: {sign}${profit:.2f}"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})
    
@api_bp.route('/deposit', methods=['POST'])
@login_required
async def deposit_route():
    t = get_t()
    data = await request.json
    bot_id = data.get('bot_id')
    try:
        amount = float(data.get('amount', 0))
    except:
        return jsonify({"status": "error", "msg": t("amount_format_error")})
    
    if amount <= 0:
        return jsonify({"status": "error", "msg": t("amount_must_be_positive")})

    lock = get_bot_lock(bot_id)
    async with lock:
        if await check_bot_ownership(bot_id) is False: 
            return jsonify({"status": "error", "msg": t("flash_unauthorized_action")})
        
        bot_data = await db.get_bot_full_data(bot_id)
        if not bot_data: return jsonify({"status": "error", "msg": t("bot_not_found")})
        
        state = bot_data['state']
        config = bot_data['config']
        
        # 1. 更新余额 (Balance)
        old_balance = float(state.get('balance', 0))
        new_balance = old_balance + amount
        state['balance'] = new_balance
        
        # 2. 更新总投入 (Capital) - 让策略知道本金增加了
        old_capital = float(config.get('capital', 0))
        new_capital = old_capital + amount
        config['capital'] = new_capital
        
        # 3. 记录日志
        await db.add_log(bot_id, t("log_deposit"), 0, amount, 0, 0, f"Deposit: +{amount} U")
        
        # 4. 保存 Config 和 State
        await db.update_bot_config(bot_id, config)
        await db.update_bot_state(bot_id, state, f"✅ {t('deposit_success')}: +{amount} U", float(bot_data.get('current_profit', 0)))
        
        return jsonify({
            "status": "success", 
            "msg": f"{t('deposit_success_msg')}\n{t('balances')}: {old_balance:.2f} -> {new_balance:.2f}\n{t('total_investment')}: {old_capital:.2f} -> {new_capital:.2f}"
        })
    
@api_bp.route('/kline/<int:bot_id>')
@login_required
async def kline_route(bot_id):
    t = get_t()
    timeframe = request.args.get('tf', '15m')
    limit = int(request.args.get('limit', 100)) 
    data = await get_bot_kline(bot_id, timeframe, limit=limit)
    if data is None:
        return jsonify({"status": "error", "msg": t("connection_failed")})
        
    return jsonify({"status": "success", "data": data})

# [修改] 2. 获取币种接口
@api_bp.route('/get_symbols')
@login_required
async def get_symbols_route():
    t = get_t()
    user = await get_current_user()
    
    # [修改] 默认为 binance，如果是 pionex 则切换
    source = user.get('exchange_source', 'binance')

    # 调用 bot_manager 中新改名的函数
    symbols = await fetch_exchange_symbols(source)
    
    if symbols:
        return jsonify({"status": "success", "symbols": symbols, "source": source})
    else:
        return jsonify({"status": "error", "msg": t("connection_failed")})

@api_bp.route('/create_folder', methods=['POST'])
@login_required
async def create_folder():
    t = get_t()
    user = await get_current_user()
    data = await request.json
    name = data.get('name')
    bot_ids = data.get('bot_ids', []) # 创建时选中的机器人ID列表

    if not name: return jsonify({"status": "error", "msg": "Name required"})

    try:
        folder_id = await db.create_folder(user['id'], name)
        # 如果选了机器人，批量更新
        for bid in bot_ids:
            await db.update_bot_folder(user['id'], bid, folder_id)
        return jsonify({"status": "success", "msg": t("folder_created")})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@api_bp.route('/delete_folder', methods=['POST'])
@login_required
async def delete_folder():
    t = get_t()
    user = await get_current_user()
    data = await request.json
    folder_id = data.get('folder_id')
    
    try:
        await db.delete_folder(user['id'], folder_id)
        return jsonify({"status": "success", "msg": t("folder_deleted")})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@api_bp.route('/move_bot', methods=['POST'])
@login_required
async def move_bot():
    t = get_t()
    user = await get_current_user()
    data = await request.json
    bot_id = data.get('bot_id')
    folder_id = data.get('folder_id') # 可以是 int 或 None
    
    try:
        await db.update_bot_folder(user['id'], bot_id, folder_id)
        return jsonify({"status": "success", "msg": t("bot_moved")})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})
    
@api_bp.route('/save_user_settings', methods=['POST'])
@login_required
async def save_user_settings():
    t = get_t()
    data = await request.json
    
    user = await get_current_user()
    if not user: return jsonify({"status": "error", "msg": "User not found"})

    need_clear_cache = False
    
    # 1. 保存语言
    if 'lang' in data:
        lang = data['lang']
        if lang in TRANSLATIONS:
            await db.update_user_language(user['id'], lang)
            session['lang'] = lang
            
    # 2. [新增] 保存交易所偏好
    if 'exchange' in data:
        exchange = data['exchange']
        if exchange in ['binance', 'pionex']: # 白名单验证
            await db.update_user_exchange(user['id'], exchange)

    # 3. [新增] 保存 API Key
    if 'api_key' in data or 'api_secret' in data:
        api_key = data.get('api_key', '').strip()
        api_secret = data.get('api_secret', '').strip()
        # 这里允许保存空字符串(相当于删除Key)
        if hasattr(db, 'update_user_api_keys'):
            await db.update_user_api_keys(user['id'], api_key, api_secret)
            need_clear_cache = True

    # [新增] 4. 执行清理操作
    if need_clear_cache:
        # 清除该用户内存中所有的旧连接实例
        await clear_user_exchange_cache(user['id'])
            
    return jsonify({"status": "success", "msg": t("config_saved")})

@api_bp.route('/start_backtest', methods=['POST'])
@login_required
async def start_backtest():
    t = get_t()
    user = await get_current_user()
    files = await request.files
    form = await request.form
    
    bot_id = form.get('bot_id')
    file = files.get('file')
    
    if not bot_id or not file:
        return jsonify({"status": "error", "msg": t("missing_bot_id_or_file")})
    
    # 验证权限
    if await check_bot_ownership(bot_id) is False:
        return jsonify({"status": "error", "msg": t("flash_unauthorized_action")})

    # 读取文件内容
    content = file.read()
    
    # 异步启动回测 (由于回测可能耗时几秒，这里直接 await 等待结果，
    # 如果文件巨大建议用 Background Task，但为了简单我们先直接 await)
    success, msg = await run_backtest(bot_id, content)
    
    if success:
        return jsonify({"status": "success", "msg": t("backtest_success_msg")})
    else:
        return jsonify({"status": "error", "msg": f"{t('backtest_failed')}: {msg}"})
    
@api_bp.route('/download_history', methods=['POST'])
@login_required
async def download_history():
    t = get_t()
    data = await request.json
    symbol = data.get('symbol', 'BTC/USDT')
    timeframe = data.get('timeframe', '15m')
    market_type = data.get('market_type', 'spot')
    
    # [修改] 获取起止日期
    start_date = data.get('start_date') # 2023-01-01
    end_date = data.get('end_date')     # 2023-01-31
    
    if not start_date or not end_date:
        return jsonify({"status": "error", "msg": t("start_date_end_date_required")})
        
    try:
        # 补全时间：00:00:00 到 23:59:59
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        if end_dt < start_dt:
            return jsonify({"status": "error", "msg": t("end_date_must_be_later")})

        start_str = start_dt.strftime('%Y-%m-%d 00:00:00')
        end_str = end_dt.strftime('%Y-%m-%d 23:59:59')
    except Exception as e:
        return jsonify({"status": "error", "msg": f"{t('date_format_error')}: {str(e)}"})

    user = await get_current_user()
    proxy = user.get('proxy_port', 0)
    source = user.get('exchange_source', 'binance')

    # 执行下载
    csv_data, err = await download_history_kline(symbol, timeframe, start_str, end_str, source, proxy, market_type)    

    if err:
        return jsonify({"status": "error", "msg": err})
    
    # 文件名包含起止日期
    filename = f"{symbol.replace('/','-')}_{market_type}_{timeframe}_{start_date}_to_{end_date}.csv"
    
    return Response(csv_data, mimetype='text/csv', headers={
        "Content-Disposition": f"attachment; filename={filename}"
    })