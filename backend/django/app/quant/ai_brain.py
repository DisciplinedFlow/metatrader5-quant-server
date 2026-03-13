"""
AI Quant Brain v2 — Comprehensive trading intelligence system.

Continuously monitors all trading domains (Forex, Crypto),
correlates with macro analysis, tracks strategy health, identifies
position-macro conflicts, and suggests strategy improvements.

Upgrades from v1:
- Integrates macro analysis from Redis cache
- Computes per-strategy performance trends (win rate, streaks, avg P&L)
- Tracks position manager activity (breakeven, partial close, swing trail)
- Calculates risk metrics (drawdown from peak, currency exposure)
- Flags position-macro alignment conflicts
- Suggests strategy parameter improvements
- Publishes strategy health scores and portfolio risk to Redis
"""
import json
import logging
import os
from collections import defaultdict
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger('app.quant.ai_brain')

AI_BRAIN_MODEL = os.getenv('AI_BRAIN_MODEL', 'claude-sonnet-4-20250514')
AI_BRAIN_MAX_TOKENS = int(os.getenv('AI_BRAIN_MAX_TOKENS', '8192'))


# ---------------------------------------------------------------------------
# Data Gathering
# ---------------------------------------------------------------------------

def gather_snapshot():
    """Collect current state from all trading domains plus macro and risk data."""
    snapshot = {
        'timestamp': timezone.now().isoformat(),
        'forex': _gather_forex(),
        'crypto': _gather_crypto(),
        'strategies': _gather_strategies(),
        'macro_analysis': _gather_macro_analysis(),
        'strategy_performance': _gather_strategy_performance(),
        'position_manager_stats': _gather_position_manager_stats(),
        'risk_metrics': _gather_risk_metrics(),
    }
    return snapshot


def _gather_forex():
    """Gather Forex positions, recent trades, bot status, regime data, and news."""
    try:
        from app.nexus.models import Trade, MarketRegime
        from app.utils.bot_control import is_bot_paused
        from django.core.cache import cache

        open_trades = Trade.objects.filter(close_time__isnull=True).values(
            'symbol', 'entry_price', 'pnl', 'order_volume', 'type', 'entry_time', 'transaction_broker_id'
        )[:20]
        recent_closed = Trade.objects.filter(
            close_time__isnull=False,
            close_time__gte=timezone.now() - timedelta(hours=24)
        ).values('symbol', 'pnl', 'type', 'entry_price', 'close_price')[:20]

        # Market regime data per pair
        regime_data = {}
        for mr in MarketRegime.objects.all():
            regime_data[mr.symbol] = {
                'regime': mr.regime,
                'adx': mr.adx,
                'bb_width': mr.bb_width,
                'atr_ratio': mr.atr_ratio,
                'confidence': mr.confidence,
            }

        # Market Pulse news (top 5 headlines)
        news = cache.get('market_pulse:news', [])[:5]

        return {
            'bot_paused': is_bot_paused(),
            'open_positions': list(open_trades),
            'recent_closed_24h': list(recent_closed),
            'total_open': len(list(open_trades)),
            'market_regimes': regime_data,
            'recent_news': news,
        }
    except Exception as e:
        logger.error(f"Error gathering forex data: {e}")
        return {'error': str(e)}


def _gather_crypto():
    """Gather crypto positions, wallet, and recent activity."""
    try:
        from app.crypto.models import CryptoPosition
        from app.crypto.bot_control import is_crypto_bot_paused

        open_positions = CryptoPosition.objects.filter(status='OPEN').values(
            'symbol', 'side', 'entry_price', 'size', 'leverage'
        )[:20]
        recent_closed = CryptoPosition.objects.filter(
            status='CLOSED',
            closed_at__gte=timezone.now() - timedelta(hours=24)
        ).values('symbol', 'side', 'pnl_usd', 'entry_price', 'close_price')[:20]

        return {
            'bot_paused': is_crypto_bot_paused(),
            'open_positions': list(open_positions),
            'recent_closed_24h': list(recent_closed),
            'total_open': len(list(open_positions)),
        }
    except Exception as e:
        logger.error(f"Error gathering crypto data: {e}")
        return {'error': str(e)}


def _gather_strategies():
    """Gather recent backtest results across all custom strategies."""
    try:
        from app.nexus.models import CustomStrategy, BacktestResult

        strategies = []
        for cs in CustomStrategy.objects.select_related('strategy_config').all()[:30]:
            bt = None
            if cs.strategy_config:
                bt = BacktestResult.objects.filter(
                    strategy=cs.strategy_config
                ).order_by('-run_time').first()
            strategies.append({
                'name': cs.name,
                'domain': cs.domain,
                'is_active': cs.strategy_config.is_active if cs.strategy_config else False,
                'total_trades': bt.total_trades if bt else 0,
                'win_rate': float(bt.win_rate) if bt else 0,
                'total_pnl': float(bt.total_pnl) if bt else 0,
                'profit_factor': float(bt.profit_factor) if bt and bt.profit_factor else 0,
                'passed': bt.passed if bt else False,
            })
        return strategies
    except Exception as e:
        logger.error(f"Error gathering strategy data: {e}")
        return {'error': str(e)}


def _gather_macro_analysis():
    """Read cached macro analysis produced by macro_analyst.py."""
    try:
        from django.core.cache import cache
        macro = cache.get('macro:analysis')
        if macro is None:
            return {'available': False, 'reason': 'No macro analysis cached'}

        # Extract the most useful fields for the AI Brain
        return {
            'available': True,
            'risk_level': macro.get('risk_level'),
            'avoid_trading': macro.get('avoid_trading', False),
            'avoid_reason': macro.get('avoid_reason', ''),
            'market_narrative': macro.get('market_narrative', ''),
            'currency_bias': macro.get('currency_bias', {}),
            'pair_signals': macro.get('pair_signals', {}),
            'upcoming_risks': macro.get('upcoming_risks', []),
            'position_advice': macro.get('position_advice', {}),
        }
    except Exception as e:
        logger.error(f"Error gathering macro analysis: {e}")
        return {'available': False, 'error': str(e)}


def _gather_strategy_performance():
    """Compute per-strategy performance trends over last 20 trades."""
    try:
        from app.nexus.models import Trade, CustomStrategy

        performance = {}
        for cs in CustomStrategy.objects.select_related('strategy_config').filter(strategy_config__isnull=False)[:20]:
            config = cs.strategy_config
            if not config:
                continue

            # Get last 20 closed trades for this strategy
            trades = Trade.objects.filter(
                strategy_config=config,
                close_time__isnull=False,
            ).order_by('-close_time')[:20]

            if not trades.exists():
                # Fallback: match by strategy name
                trades = Trade.objects.filter(
                    strategy__icontains=cs.name,
                    close_time__isnull=False,
                ).order_by('-close_time')[:20]

            pnls = [t.pnl for t in trades if t.pnl is not None]
            if not pnls:
                performance[cs.name] = {
                    'trade_count': 0,
                    'note': 'No closed trades found',
                }
                continue

            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]

            # Consecutive wins/losses (from most recent)
            consecutive_wins = 0
            consecutive_losses = 0
            for p in pnls:
                if p > 0:
                    consecutive_wins += 1
                else:
                    break
            for p in pnls:
                if p <= 0:
                    consecutive_losses += 1
                else:
                    break

            # Per-symbol breakdown of recent trades
            symbol_pnl = defaultdict(list)
            for t in trades:
                if t.pnl is not None:
                    symbol_pnl[t.symbol].append(t.pnl)

            # Time-of-day analysis for losing trades
            losing_hours = defaultdict(int)
            for t in trades:
                if t.pnl is not None and t.pnl < 0 and t.entry_time:
                    losing_hours[t.entry_time.hour] += 1

            performance[cs.name] = {
                'trade_count': len(pnls),
                'win_rate': round(len(wins) / len(pnls), 4) if pnls else 0,
                'avg_pnl': round(sum(pnls) / len(pnls), 4) if pnls else 0,
                'avg_win': round(sum(wins) / len(wins), 4) if wins else 0,
                'avg_loss': round(sum(losses) / len(losses), 4) if losses else 0,
                'total_pnl': round(sum(pnls), 4),
                'consecutive_wins': consecutive_wins,
                'consecutive_losses': consecutive_losses,
                'is_active': config.is_active,
                'symbol_performance': {
                    sym: {
                        'trades': len(vals),
                        'total_pnl': round(sum(vals), 4),
                        'win_rate': round(len([v for v in vals if v > 0]) / len(vals), 4) if vals else 0,
                    }
                    for sym, vals in symbol_pnl.items()
                },
                'losing_trade_hours': dict(losing_hours) if losing_hours else {},
            }

        return performance
    except Exception as e:
        logger.error(f"Error gathering strategy performance: {e}")
        return {'error': str(e)}


def _gather_position_manager_stats():
    """Count position manager activity from Trade records."""
    try:
        from app.nexus.models import Trade

        # Stats over last 7 days
        since = timezone.now() - timedelta(days=7)
        recent_trades = Trade.objects.filter(
            entry_time__gte=since,
        )

        total = recent_trades.count()
        breakeven_count = recent_trades.filter(breakeven_moved=True).count()
        partial_close_count = recent_trades.filter(partial_closed=True).count()

        # For open trades, check current state
        open_trades = Trade.objects.filter(close_time__isnull=True)
        open_with_breakeven = open_trades.filter(breakeven_moved=True).count()
        open_with_partial = open_trades.filter(partial_closed=True).count()

        return {
            'period': '7d',
            'total_trades': total,
            'breakeven_moves': breakeven_count,
            'partial_closes': partial_close_count,
            'breakeven_rate': round(breakeven_count / total, 4) if total > 0 else 0,
            'partial_close_rate': round(partial_close_count / total, 4) if total > 0 else 0,
            'open_positions': {
                'total': open_trades.count(),
                'at_breakeven': open_with_breakeven,
                'partially_closed': open_with_partial,
            },
        }
    except Exception as e:
        logger.error(f"Error gathering position manager stats: {e}")
        return {'error': str(e)}


def _gather_risk_metrics():
    """Calculate portfolio risk metrics: drawdown, currency exposure."""
    try:
        from app.nexus.models import Trade
        from django.db.models import Sum, Max

        # --- Drawdown from peak equity ---
        # Compute cumulative P&L from all closed trades
        closed_trades = Trade.objects.filter(
            close_time__isnull=False,
            pnl__isnull=False,
        ).order_by('close_time').values_list('pnl', flat=True)

        pnl_list = list(closed_trades)
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for pnl in pnl_list:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_drawdown:
                max_drawdown = dd

        current_drawdown = peak - cumulative if peak > cumulative else 0.0

        # --- Currency exposure from open positions ---
        open_trades = Trade.objects.filter(close_time__isnull=True)
        currency_exposure = defaultdict(lambda: {'long': 0.0, 'short': 0.0, 'net_volume': 0.0})
        for t in open_trades:
            symbol = t.symbol
            vol = t.order_volume or 0.0
            if len(symbol) >= 6:
                base = symbol[:3]
                quote = symbol[3:6]
                if t.type == 'BUY':
                    currency_exposure[base]['long'] += vol
                    currency_exposure[quote]['short'] += vol
                else:
                    currency_exposure[base]['short'] += vol
                    currency_exposure[quote]['long'] += vol
                currency_exposure[base]['net_volume'] = (
                    currency_exposure[base]['long'] - currency_exposure[base]['short']
                )
                currency_exposure[quote]['net_volume'] = (
                    currency_exposure[quote]['long'] - currency_exposure[quote]['short']
                )

        # --- Recent P&L trajectory (last 7 days) ---
        week_ago = timezone.now() - timedelta(days=7)
        recent_pnl = Trade.objects.filter(
            close_time__isnull=False,
            close_time__gte=week_ago,
            pnl__isnull=False,
        ).aggregate(total=Sum('pnl'))['total'] or 0.0

        return {
            'cumulative_pnl': round(cumulative, 2),
            'peak_equity': round(peak, 2),
            'current_drawdown': round(current_drawdown, 2),
            'max_drawdown_ever': round(max_drawdown, 2),
            'drawdown_pct': round((current_drawdown / peak) * 100, 2) if peak > 0 else 0.0,
            'currency_exposure': {k: dict(v) for k, v in currency_exposure.items()},
            'pnl_last_7d': round(recent_pnl, 2),
            'total_closed_trades': len(pnl_list),
        }
    except Exception as e:
        logger.error(f"Error gathering risk metrics: {e}")
        return {'error': str(e)}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def run_analysis():
    """Main entry point -- gather data, send to Claude, return structured analysis."""
    api_key = os.getenv('ANTHROPIC_API_KEY', '')
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set, skipping AI brain analysis")
        return None

    snapshot = gather_snapshot()

    # Log key data points before sending to Claude
    risk = snapshot.get('risk_metrics', {})
    perf = snapshot.get('strategy_performance', {})
    pm = snapshot.get('position_manager_stats', {})
    forex = snapshot.get('forex', {})
    macro = snapshot.get('macro_analysis', {})
    logger.info(
        f"AI Brain snapshot gathered: "
        f"open_positions={forex.get('total_open', 0)}, "
        f"drawdown=${risk.get('current_drawdown', 0):.2f}, "
        f"7d_pnl=${risk.get('pnl_last_7d', 0):.2f}, "
        f"strategies_tracked={len(perf) if isinstance(perf, dict) else 0}, "
        f"macro_available={macro.get('available', False)}, "
        f"pm_breakeven_rate={pm.get('breakeven_rate', 0):.1%}"
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        system_prompt = _build_system_prompt()

        response = client.messages.create(
            model=AI_BRAIN_MODEL,
            max_tokens=AI_BRAIN_MAX_TOKENS,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"Current portfolio snapshot:\n{json.dumps(snapshot, indent=2, default=str)}"
            }],
        )

        text = response.content[0].text.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()

        analysis = json.loads(text)
        analysis['_meta'] = {
            'model': AI_BRAIN_MODEL,
            'timestamp': timezone.now().isoformat(),
            'input_tokens': response.usage.input_tokens,
            'output_tokens': response.usage.output_tokens,
        }

        # Store in Redis for dashboard (backward-compatible)
        from .ai_bot_control import store_analysis
        store_analysis(analysis)

        # Cache per-position recommendations for the Adaptive Trading Engine
        from django.core.cache import cache
        recommendations = analysis.get('position_recommendations', {})
        for ticket, rec in recommendations.items():
            cache.set(f'ai_brain:position:{ticket}', rec, timeout=600)  # 10-minute TTL

        # NEW: Cache strategy health scores
        strategy_health = _build_strategy_health(analysis, snapshot)
        cache.set('ai_brain:strategy_health', json.dumps(strategy_health, default=str), timeout=3600)

        # NEW: Cache portfolio risk summary
        portfolio_risk = _build_portfolio_risk(analysis, snapshot)
        cache.set('ai_brain:portfolio_risk', json.dumps(portfolio_risk, default=str), timeout=3600)

        # Log key metrics from the analysis
        logger.info(
            f"AI Brain analysis complete: "
            f"regime={analysis.get('market_regime')}, "
            f"risk_score={analysis.get('risk_score')}, "
            f"alerts={len(analysis.get('risk_alerts', []))}, "
            f"conflicts={len(analysis.get('position_macro_conflicts', []))}, "
            f"improvements={len(analysis.get('strategy_improvements', []))}, "
            f"tokens_in={response.usage.input_tokens}, "
            f"tokens_out={response.usage.output_tokens}"
        )
        return analysis

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI brain response: {e}")
        return None
    except Exception as e:
        logger.error(f"AI Brain error: {e}")
        return None


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

def _build_system_prompt():
    """Build the comprehensive trading desk manager prompt."""
    return """You are the head of a quantitative trading desk managing a multi-asset portfolio across:
1. **Forex** (MetaTrader 5) -- currency pairs with CVD-based, mean reversion & scalping strategies
2. **Crypto** (Hyperliquid) -- BTC, ETH, SOL etc with momentum & CVD-based strategies

You receive a comprehensive snapshot including:
- Open positions and recent trades across all domains
- Market regime data (ADX, Bollinger Band width, ATR ratio) per pair
- Macro analysis from a senior forex macro analyst (currency biases, risk level, upcoming events)
- Per-strategy performance trends (win rate, avg P&L, consecutive wins/losses over last 20 trades)
- Position manager activity (breakeven moves, partial closes, swing trail stats)
- Risk metrics (drawdown from peak equity, currency exposure, 7-day P&L)

YOUR JOB is to act as the trading desk manager who:
1. Monitors all open positions and their risk/reward status
2. Evaluates whether active strategies are performing as expected
3. Correlates macro analysis with current positions (flag conflicts!)
4. Suggests specific strategy parameter adjustments based on recent performance
5. Identifies patterns in losing trades (time of day, pair, direction)
6. Provides a confidence score for each strategy continuing to work
7. Flags positions that conflict with the current macro view

RESPOND WITH ONLY A JSON OBJECT (no markdown, no backticks) with this structure:
{
    "market_regime": "risk_on|risk_off|neutral|volatile",
    "risk_score": 1-10,
    "regime_summary": "One sentence describing current market conditions",
    "risk_alerts": ["list of immediate concerns"],
    "forex_analysis": {
        "summary": "brief assessment",
        "recommendations": ["actionable items"]
    },
    "crypto_analysis": {
        "summary": "brief assessment",
        "recommendations": ["actionable items"]
    },
    "strategy_insights": ["observations about strategy performance"],
    "strategy_improvements": [
        {
            "strategy_name": "exact strategy name",
            "suggestion": "what to change and why",
            "parameter_changes": {"param_name": "new_value"},
            "reasoning": "data-driven explanation referencing recent performance metrics",
            "confidence_score": 1-10
        }
    ],
    "position_macro_conflicts": [
        {
            "symbol": "EURUSD",
            "position_direction": "BUY",
            "macro_bias": "bearish",
            "recommendation": "TIGHTEN|EXIT|HOLD|REDUCE",
            "urgency": "high|medium|low",
            "reason": "brief explanation of the conflict"
        }
    ],
    "new_strategy_ideas": [
        {
            "name": "strategy name",
            "domain": "FOREX|CRYPTO",
            "description": "what it does",
            "edge": "why it should work",
            "parameters": {"key": "value"}
        }
    ],
    "portfolio_actions": ["specific actions to take now"],
    "position_recommendations": {
        "<ticket_or_broker_id>": {
            "action": "HOLD|TIGHTEN|EXIT|SCALE_OUT",
            "reason": "why this action",
            "suggested_sl": null
        }
    },
    "strategy_health": {
        "<strategy_name>": {
            "health_score": 1-10,
            "trend": "improving|stable|degrading",
            "concerns": ["list of specific concerns"],
            "strengths": ["list of what is working"]
        }
    },
    "portfolio_risk_assessment": {
        "overall_risk": "low|moderate|elevated|high|critical",
        "concentration_risk": "description of any concentration issues",
        "correlation_risk": "description of correlated positions",
        "max_recommended_positions": 5,
        "capital_at_risk_pct": 0.0
    }
}

CRITICAL ANALYSIS RULES:
- For position_macro_conflicts: Compare EVERY open forex position's direction against the macro currency_bias. If you're long a pair where the base currency has a bearish macro bias (confidence >= 5) or the quote currency has a bullish macro bias, flag it. Vice versa for shorts.
- For strategy_improvements: Reference actual numbers from strategy_performance (win rate, avg P&L, consecutive losses). Suggest concrete parameter changes (sl_multiplier, tp_multiplier, entry_threshold).
- For strategy_health: Assign health_score based on: win rate vs expected (from backtest), consecutive losses, trend direction. Score < 4 means strategy should be reviewed for deactivation.
- For losing trade patterns: Check losing_trade_hours and symbol_performance to identify if losses cluster at specific times or pairs.
- When macro says avoid_trading=true, recommend EXIT or TIGHTEN for ALL open positions.
- Position manager stats inform whether the adaptive management is working (high breakeven_rate = good, low = entries may be poor quality).

For each open position (identified by transaction_broker_id), provide a recommendation:
- HOLD: Position is well-managed, keep current SL/TP
- TIGHTEN: Move SL closer to current price (specify suggested level in "suggested_sl")
- EXIT: Close the position immediately (explain why in "reason")
- SCALE_OUT: Close 50% of position to lock in partial profit

Be concise, data-driven, and specific. Don't hedge -- give clear recommendations with reasoning."""


# ---------------------------------------------------------------------------
# Post-analysis Redis caching
# ---------------------------------------------------------------------------

def _build_strategy_health(analysis, snapshot):
    """Build per-strategy health scores for Redis caching."""
    health = {}

    # Use Claude's strategy_health output if available
    ai_health = analysis.get('strategy_health', {})

    # Merge with raw performance data
    perf = snapshot.get('strategy_performance', {})
    strategies = snapshot.get('strategies', [])

    for strategy in strategies:
        name = strategy.get('name', '')
        ai_entry = ai_health.get(name, {})
        perf_entry = perf.get(name, {})

        health[name] = {
            'health_score': ai_entry.get('health_score', 5),
            'trend': ai_entry.get('trend', 'stable'),
            'concerns': ai_entry.get('concerns', []),
            'strengths': ai_entry.get('strengths', []),
            'is_active': strategy.get('is_active', False),
            'live_win_rate': perf_entry.get('win_rate', 0),
            'live_avg_pnl': perf_entry.get('avg_pnl', 0),
            'live_total_pnl': perf_entry.get('total_pnl', 0),
            'consecutive_wins': perf_entry.get('consecutive_wins', 0),
            'consecutive_losses': perf_entry.get('consecutive_losses', 0),
            'backtest_win_rate': strategy.get('win_rate', 0),
            'backtest_pnl': strategy.get('total_pnl', 0),
            'backtest_passed': strategy.get('passed', False),
        }

    return health


def _build_portfolio_risk(analysis, snapshot):
    """Build portfolio risk summary for Redis caching."""
    risk_metrics = snapshot.get('risk_metrics', {})
    ai_risk = analysis.get('portfolio_risk_assessment', {})
    forex = snapshot.get('forex', {})
    macro = snapshot.get('macro_analysis', {})
    pm = snapshot.get('position_manager_stats', {})
    conflicts = analysis.get('position_macro_conflicts', [])

    return {
        'timestamp': snapshot.get('timestamp'),
        'market_regime': analysis.get('market_regime', 'unknown'),
        'risk_score': analysis.get('risk_score', 5),
        'regime_summary': analysis.get('regime_summary', ''),
        'overall_risk': ai_risk.get('overall_risk', 'moderate'),
        'concentration_risk': ai_risk.get('concentration_risk', ''),
        'correlation_risk': ai_risk.get('correlation_risk', ''),
        'max_recommended_positions': ai_risk.get('max_recommended_positions', 5),
        'capital_at_risk_pct': ai_risk.get('capital_at_risk_pct', 0),
        'cumulative_pnl': risk_metrics.get('cumulative_pnl', 0),
        'peak_equity': risk_metrics.get('peak_equity', 0),
        'current_drawdown': risk_metrics.get('current_drawdown', 0),
        'max_drawdown_ever': risk_metrics.get('max_drawdown_ever', 0),
        'drawdown_pct': risk_metrics.get('drawdown_pct', 0),
        'pnl_last_7d': risk_metrics.get('pnl_last_7d', 0),
        'currency_exposure': risk_metrics.get('currency_exposure', {}),
        'open_positions': forex.get('total_open', 0),
        'macro_risk_level': macro.get('risk_level', 0),
        'macro_avoid_trading': macro.get('avoid_trading', False),
        'position_macro_conflicts': len(conflicts),
        'position_manager': {
            'breakeven_rate': pm.get('breakeven_rate', 0),
            'partial_close_rate': pm.get('partial_close_rate', 0),
        },
        'risk_alerts': analysis.get('risk_alerts', []),
    }
