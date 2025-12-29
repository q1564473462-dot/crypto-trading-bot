import os
import urllib.request # [新增] 用于探测系统代理
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# ============================================================
# [新增] 自动检测并应用系统代理 (让 aiohttp 能像 ccxt 一样自动走梯子)
# ============================================================
try:
    # 获取系统当前的代理设置 (Windows/Mac 的系统代理)
    sys_proxies = urllib.request.getproxies()
    
    # 如果系统有设置 http 代理，且环境变量里没手动指定，就自动应用系统的
    if 'http' in sys_proxies and not os.environ.get('HTTP_PROXY'):
        print(f">>> 🔗 自动检测到系统代理 (HTTP): {sys_proxies['http']}")
        os.environ['HTTP_PROXY'] = sys_proxies['http']
        
    # 同上，处理 https 代理
    if 'https' in sys_proxies and not os.environ.get('HTTPS_PROXY'):
        print(f">>> 🔗 自动检测到系统代理 (HTTPS): {sys_proxies['https']}")
        os.environ['HTTPS_PROXY'] = sys_proxies['https']
        
except Exception as e:
    print(f"⚠️ 自动代理检测失败: {e}")
# ============================================================

# 数据库配置字典
DB_CONFIG = {
    'host': os.getenv('DB_HOST', '127.0.0.1'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASS', ''),
    'db': os.getenv('DB_NAME', 'crypto_bot_db'),
    'charset': 'utf8mb4',
    'autocommit': True
}