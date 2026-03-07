import logging

logger = logging.getLogger('app.crypto')


def calculate_position_size(
    capital: float,
    current_price: float,
    max_position_pct: float = 0.10,
    leverage: int = 1,
) -> float:
    position_value = capital * max_position_pct * leverage
    size = position_value / current_price
    return size


def check_position_limits(
    open_position_count: int,
    max_positions: int,
) -> bool:
    return open_position_count < max_positions
