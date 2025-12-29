# utils.py
from quart import session, redirect, url_for, flash
from functools import wraps
from modules.database import db
from languages import TRANSLATIONS

# --- 1. 翻译辅助函数 ---
def get_t():
    """ 获取当前会话语言的翻译函数 """
    lang = session.get('lang', 'zh-CN')
    def t(key):
        return TRANSLATIONS.get(lang, TRANSLATIONS['zh-CN']).get(key, key)
    return t

# --- 2. 用户获取函数 ---
async def get_current_user():
    if 'user_id' in session:
        return await db.get_user_by_id(session['user_id'])
    return None

# --- 3. 权限验证装饰器 ---
def login_required(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            # 注意：这里 url_for 指向的是 auth 蓝图下的 login
            return redirect(url_for('auth.login')) 
        return await func(*args, **kwargs)
    return wrapper

def admin_required(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        t = get_t()
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        user = await get_current_user()
        if not user or not user.get('is_admin'):
            await flash(t("need_admin"), 'danger')
            # 注意：这里 url_for 指向 web 蓝图下的 dashboard
            return redirect(url_for('web.dashboard')) 
        return await func(*args, **kwargs)
    return wrapper

# --- 4. 机器人所有权检查 ---
async def check_bot_ownership(bot_id):
    user = await get_current_user()
    if not user: return False
    bot = await db.get_bot_full_data(bot_id)
    if not bot: return None
    if bot['user_id'] != user['id']: return False
    return bot