# routes/auth.py
from quart import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from modules.database import db
from utils import get_t, get_current_user

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
async def login():
    # [新增] 处理 URL 传参切换语言 (例如 ?lang=en)
    lang_arg = request.args.get('lang')
    if lang_arg in ['zh-CN', 'zh-TW', 'en']:
        session['lang'] = lang_arg

    if await get_current_user():
        return redirect(url_for('web.dashboard'))
        
    if request.method == 'POST':
        form = await request.form
        username = form.get('username')
        password = form.get('password')

        # 获取当前会话语言
        current_lang = session.get('lang', 'zh-CN')
        t = get_t()
        
        user_data = await db.get_user_by_username(username)
        if user_data and check_password_hash(user_data['password_hash'], password):
            # [新增] 登录成功，强制更新用户的数据库语言设置
            await db.update_user_language(user_data['id'], current_lang)

            session['user_id'] = user_data['id']
            session['username'] = user_data['username']
            session['is_admin'] = user_data.get('is_admin', 0)
            session['lang'] = current_lang  # 确保 session 语言同步
            return redirect(url_for('web.dashboard'))
        else:
            await flash(t('login_failed') or '用户名或密码错误')

    return await render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
async def register():
    # [新增] 处理 URL 传参切换语言
    lang_arg = request.args.get('lang')
    if lang_arg in ['zh-CN', 'zh-TW', 'en']:
        session['lang'] = lang_arg

    if await get_current_user():
        return redirect(url_for('web.dashboard'))
        
    if request.method == 'POST':
        form = await request.form
        username = form.get('username')
        password = form.get('password')
        
        # 获取当前会话语言
        current_lang = session.get('lang', 'zh-CN')
        t = get_t()
        
        if not username or not password:
            await flash(t('Please_provide_complete_information'))
        elif await db.get_user_by_username(username):
            await flash(t('username_exists'))
        else:
            hashed_pw = generate_password_hash(password)
            # [新增] 创建用户时记录语言
            await db.create_user(username, hashed_pw, language=current_lang)
            
            # === [修复的部分在这里] ===
            # 直接调用 t()，不要用 in 判断
            await flash(t('registration_success')) 
            # =======================
            
            return redirect(url_for('auth.login'))
            
    return await render_template('register.html')

@auth_bp.route('/logout')
async def logout():
    session.clear()
    return redirect(url_for('auth.login'))