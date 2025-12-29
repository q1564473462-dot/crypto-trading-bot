# routes/web.py
from quart import Blueprint, render_template, url_for, session, request, flash, redirect
from modules.database import db
from utils import get_t, get_current_user, login_required
from modules.exchange_manager import clear_user_exchange_cache

web_bp = Blueprint('web', __name__)

@web_bp.route('/')
@login_required
async def dashboard():
    user = await get_current_user()
    
    # [新增] 获取 URL 中的 mode 参数，默认为 'live'
    mode = request.args.get('mode', 'live')
    
    # 传给数据库查询
    bots = await db.get_all_bots(user['id'], mode=mode)
    
    folders = await db.get_user_folders(user['id'])
    return await render_template('dashboard.html', bots=bots, folders=folders, user=user)


@web_bp.route('/bot/<int:bot_id>')
@login_required
async def bot_detail(bot_id):
    t = get_t()
    user = await get_current_user()
    bot = await db.get_bot_full_data(bot_id)
    if not bot: return "Bot not found", 404
    if bot['user_id'] != user['id'] and not user.get('is_admin'):
        return t("no_permission_to_access_this_bot"), 403
    
    s_type = bot.get('strategy_type', 'fvg')
    if s_type == 'coffin':
        template = 'bot_detail_coffin.html'
    elif s_type == 'grid_dca':
        template = 'bot_grid_dca.html'
    elif s_type == 'periodic':           # [新增]
        template = 'bot_periodic.html'
    else:
        template = 'bot_detail.html'

    back_url = url_for('web.dashboard')
    if user.get('is_admin') and bot['user_id'] != user['id']:
        back_url = url_for('admin.view_user_bots', user_id=bot['user_id'])
        
    return await render_template(template, bot_id=bot_id, bot=bot, user=user, back_url=back_url)

@web_bp.route('/settings', methods=['GET', 'POST']) # [修改] 增加 POST 方法
@login_required
async def settings():
    user = await get_current_user()
    t = get_t() # 获取翻译函数

    # [新增] 处理保存设置的逻辑
    if request.method == 'POST':
        form = await request.form
        
        # 1. 获取表单数据
        api_key = form.get('api_key')
        api_secret = form.get('api_secret')
        exchange_source = form.get('exchange_source') # 例如 'binance' 或 'pionex'
        
        # 2. 更新数据库
        # 注意：这里假设你数据库有这两个 update 方法，如果 database.py 里没有，你需要确认一下
        if api_key is not None: # 允许空字符串（清空Key）
            await db.update_user_api_keys(user['id'], api_key, api_secret)
        
        if exchange_source:
            await db.update_user_exchange(user['id'], exchange_source)

        # 3. [核心修复] 清理该用户的旧交易所连接缓存
        # 这会调用旧连接的 .close()，防止 "Unclosed client session" 报错
        # 下次机器人循环时，get_cached_exchange 发现缓存空了，就会用新 Key 创建新连接
        await clear_user_exchange_cache(user['id'])

        await flash(t('config_saved') or "配置已保存")
        return redirect(url_for('web.settings'))

    # GET 请求逻辑保持不变
    user['pionex_api_key'] = user.get('api_key')
    user['pionex_api_secret'] = user.get('api_secret')
    if user.get('exchange_source') == 'binance':
        user['api_key'] = user.get('binance_api_key')
        user['api_secret'] = user.get('binance_api_secret')
    return await render_template('settings.html', user=user)