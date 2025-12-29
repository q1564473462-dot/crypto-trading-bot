import asyncio
from decimal import Decimal, ROUND_DOWN

# ================= 全局缓存与锁 =================

RUNTIME_CACHE = {} 
WS_PRICE_CACHE = {}
BOT_LOCKS = {}
EXCHANGE_CACHE = {}

def get_bot_lock(bot_id):
    if bot_id not in BOT_LOCKS:
        BOT_LOCKS[bot_id] = asyncio.Lock()
    return BOT_LOCKS[bot_id]

def adjust_precision(value, precision):
    if value == 0: return 0.0
    if precision == 0: return float(value)
    val_d = Decimal(str(value))
    prec_d = Decimal(str(precision))
    quantized = (val_d / prec_d).to_integral_value(rounding=ROUND_DOWN) * prec_d
    return float(quantized)