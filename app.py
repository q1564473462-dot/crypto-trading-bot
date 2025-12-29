import os
import asyncio
from quart import Quart, session
from modules.database import db
from modules.bot_manager import bot_engine_loop, close_all_exchanges
from languages import TRANSLATIONS

# 导入蓝图
from routes.auth import auth_bp
from routes.web import web_bp
from routes.api import api_bp
from routes.admin import admin_bp

app = Quart(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'async_quant_secret_key_888')

# ================= 注册蓝图 =================
app.register_blueprint(auth_bp)
app.register_blueprint(web_bp)
app.register_blueprint(api_bp)
app.register_blueprint(admin_bp)

# ================= 上下文处理器 (全局变量) =================
@app.context_processor
def inject_translations():
    lang = session.get('lang', 'zh-CN')
    t = TRANSLATIONS.get(lang, TRANSLATIONS['zh-CN'])
    return dict(t=t, current_lang=lang)

# ================= 生命周期钩子 =================

@app.before_serving
async def startup():
    await db.init_pool()
    app.add_background_task(bot_engine_loop)

@app.after_serving
async def shutdown():
    print("\n>>> 正在优雅退出，清理资源...")
    await close_all_exchanges()
    await db.close()
    print(">>> 资源已释放，安全退出。")

if __name__ == '__main__':
    print(">>> 启动高性能异步量化系统 (Quart + Asyncio)")
    app.run(debug=True, port=5000, use_reloader=False)