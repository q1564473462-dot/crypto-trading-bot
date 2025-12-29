from .fvg import FVGStrategy
from .coffin import CoffinStrategy  # 修改引用
from .grid_dca import GridDCAStrategy
from .periodic import PeriodicStrategy

STRATEGY_MAP = {
    'fvg': FVGStrategy,
    'coffin': CoffinStrategy,       # 修改映射键
    'grid_dca': GridDCAStrategy,
    'periodic': PeriodicStrategy,
}

def get_strategy_class(strategy_type):
    return STRATEGY_MAP.get(strategy_type, FVGStrategy)