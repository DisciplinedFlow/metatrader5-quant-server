import logging
import pandas as pd
from django.utils import timezone

from .client import get_all_mids, get_candles, close_position
from .strategy import MomentumStrategy
from .config import CRYPTO_FAST_MA, CRYPTO_SLOW_MA, CRYPTO_LOOKBACK, CRYPTO_MAX_POSITION_PCT

logger = logging.getLogger('app.crypto')


def exit_algorithm():
    """Monitor open positions and exit on signal reversal or stop-loss/take-profit."""
    from app.crypto.models import CryptoPosition, CryptoTrade

    open_positions = CryptoPosition.objects.filter(status='OPEN')
    if not open_positions.exists():
        return

    mids = get_all_mids()
    strategy = MomentumStrategy(
        signal_type='ma_crossover',
        fast_ma=CRYPTO_FAST_MA,
        slow_ma=CRYPTO_SLOW_MA,
        lookback=CRYPTO_LOOKBACK,
        max_position_pct=CRYPTO_MAX_POSITION_PCT,
    )

    for position in open_positions:
        try:
            current_price = float(mids.get(position.symbol, 0))
            if current_price <= 0:
                continue

            close_reason = None

            # Check stop loss
            if position.stop_loss:
                if position.side == 'LONG' and current_price <= position.stop_loss:
                    close_reason = 'STOP_LOSS'
                elif position.side == 'SHORT' and current_price >= position.stop_loss:
                    close_reason = 'STOP_LOSS'

            # Check take profit
            if not close_reason and position.take_profit:
                if position.side == 'LONG' and current_price >= position.take_profit:
                    close_reason = 'TAKE_PROFIT'
                elif position.side == 'SHORT' and current_price <= position.take_profit:
                    close_reason = 'TAKE_PROFIT'

            # Check signal reversal
            if not close_reason:
                try:
                    candles = get_candles(position.symbol, interval='1h', limit=max(CRYPTO_SLOW_MA + 50, 300))
                    if candles:
                        closes = pd.Series([float(c['c']) for c in candles])
                        signal = strategy.generate_signal(closes)
                        if position.side == 'LONG' and signal <= 0:
                            close_reason = 'SIGNAL_REVERSAL'
                        elif position.side == 'SHORT' and signal >= 0:
                            close_reason = 'SIGNAL_REVERSAL'
                except Exception as e:
                    logger.warning(f"Signal check error for {position.symbol}: {e}")

            if close_reason:
                logger.info(f"Exit signal: {position.symbol} {position.side} reason={close_reason} price={current_price}")

                result = close_position(position.symbol)

                if position.side == 'LONG':
                    pnl = (current_price - position.entry_price) * position.size
                else:
                    pnl = (position.entry_price - current_price) * position.size

                position.status = 'CLOSED'
                position.close_price = current_price
                position.pnl_usd = pnl
                position.close_reason = close_reason
                position.closed_at = timezone.now()
                position.save()

                CryptoTrade.objects.create(
                    position=position,
                    order_id=str(result) if result else '',
                    side='SELL' if position.side == 'LONG' else 'BUY',
                    price=current_price,
                    size=position.size,
                    status='FILLED',
                )

                logger.info(f"Position closed: {position.symbol} pnl=${pnl:.2f} reason={close_reason}")

        except Exception as e:
            logger.error(f"Exit error for {position.symbol}: {e}")
