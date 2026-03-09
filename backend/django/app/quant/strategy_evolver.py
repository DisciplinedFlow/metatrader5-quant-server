"""
Strategy Evolution Engine
=========================

An autonomous system that uses Claude to research, generate, backtest,
and promote/retire forex trading strategies.

Runs as a periodic Celery task (daily). The pipeline:

1. **Audit** current strategies -- identify gaps and failures
2. **Research** new strategy ideas via Claude (claude-sonnet-4-6)
3. **Generate** strategy definition JSON via Claude (claude-haiku-4-5-20251001)
4. **Backtest** each candidate with GenericBacktester
5. **Promote** winners by creating CustomStrategy + StrategyConfig records
6. **Retire** underperformers based on live + backtest results

Only indicators present in INDICATOR_REGISTRY are allowed.
"""

import json
import logging
import os
import traceback
from datetime import datetime, timedelta

import anthropic
from django.db import transaction
from django.utils import timezone

from app.nexus.models import BacktestResult, CustomStrategy, StrategyConfig
from app.quant.backtester_generic import CONDITION_OPS, INDICATOR_REGISTRY, GenericBacktester

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESEARCH_MODEL = "claude-sonnet-4-6"
GENERATION_MODEL = "claude-haiku-4-5-20251001"

FOREX_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
    "NZDUSD", "USDCAD", "USDCHF", "EURGBP",
]

VALID_TIMEFRAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]

DOMAIN = "FOREX"

# Promotion thresholds
MIN_WIN_RATE = 0.45
MIN_TOTAL_PNL = 0.0
MIN_TOTAL_TRADES = 50
MIN_PROFIT_FACTOR = 1.2

# Retirement thresholds
MAX_CONSECUTIVE_FAILED_BACKTESTS = 3
MAX_STRATEGIES_TO_GENERATE = 5

# Build the system prompt context once
AVAILABLE_INDICATORS = sorted(INDICATOR_REGISTRY.keys())
AVAILABLE_CONDITIONS = sorted(CONDITION_OPS.keys())

# Numeric conditions usable with numeric indicators (RSI, ATR, etc.)
NUMERIC_CONDITIONS = ["eq", "gt", "gte", "lt", "lte"]

# String-match conditions (for signal-based indicators)
SIGNAL_CONDITIONS = [
    c for c in AVAILABLE_CONDITIONS if c not in NUMERIC_CONDITIONS
]

# Indicators that return numeric values vs. signal strings
NUMERIC_INDICATORS = ["RSI", "ATR", "CVD_RAW"]
SIGNAL_INDICATORS = [
    ind for ind in AVAILABLE_INDICATORS if ind not in NUMERIC_INDICATORS
]

# Map indicators to the conditions they can use and their parameter schemas
INDICATOR_DOCS = {
    "EMA_CROSSOVER": {
        "description": "EMA crossover: returns 'bull_cross' or 'bear_cross' signals",
        "params": {"fast": "int (default 9)", "slow": "int (default 21)"},
        "valid_conditions": ["divergence"],
        "signal_values": {
            "long": "bull_cross",
            "short": "bear_cross",
        },
    },
    "RSI": {
        "description": "Relative Strength Index: returns numeric 0-100",
        "params": {"period": "int (default 14)"},
        "valid_conditions": NUMERIC_CONDITIONS,
        "example_rules": {
            "long": {"condition": "lt", "value": 30},
            "short": {"condition": "gt", "value": 70},
        },
    },
    "ATR": {
        "description": "Average True Range: returns numeric volatility value. Mainly used in exit rules, not entry.",
        "params": {"period": "int (default 14)"},
        "valid_conditions": NUMERIC_CONDITIONS,
    },
    "BOLLINGER_BANDS": {
        "description": "Mean reversion via Bollinger Bands: returns 'top' or 'bottom' signals when price crosses bands",
        "params": {"window": "int (default 20)", "num_std_dev": "float (default 2)"},
        "valid_conditions": ["divergence"],
        "signal_values": {
            "long": "bottom",
            "short": "top",
        },
    },
    "CVD": {
        "description": "CVD Divergence: detects lack_of_participants and absorption patterns",
        "params": {"lookback": "int (default 20)", "swing_lookback": "int (default 5)"},
        "valid_conditions": ["divergence"],
        "signal_values": {
            "long": "bullish_lack_of_participants or bullish_absorption",
            "short": "bearish_lack_of_participants or bearish_absorption",
        },
    },
    "CVD_RAW": {
        "description": "Raw CVD values (numeric). Use for overlay/visualization.",
        "params": {"lookback": "int (default 20)"},
        "valid_conditions": NUMERIC_CONDITIONS,
    },
    "CVD_LEADING": {
        "description": "Leading CVD: early exhaustion detection via delta momentum",
        "params": {"lookback": "int (default 10)", "swing_lookback": "int (default 5)"},
        "valid_conditions": ["leading_divergence", "leading_volume"],
        "signal_values": {
            "long": "bullish_exhaustion_early",
            "short": "bearish_exhaustion_early",
        },
    },
    "CVD_EXTREMES": {
        "description": "CVD at extreme price points with wider lookback",
        "params": {"lookback": "int (default 50)", "swing_lookback": "int (default 5)", "strength": "int (default 3)"},
        "valid_conditions": ["extreme_divergence"],
        "signal_values": {
            "long": "bullish_extreme",
            "short": "bearish_extreme",
        },
    },
    "CVD_MTF": {
        "description": "Multi-timeframe CVD: divergence confirmed across multiple lookback scales",
        "params": {"lookback": "int (default 20)", "swing_lookback": "int (default 5)"},
        "valid_conditions": ["mtf_divergence"],
        "signal_values": {
            "long": "bullish_mtf_confirmed",
            "short": "bearish_mtf_confirmed",
        },
    },
    "CVD_CROSS_MARKET": {
        "description": "Cross-market CVD: compares volume-weighted vs price-only delta. Needs volume data.",
        "params": {"lookback": "int (default 20)", "swing_lookback": "int (default 5)"},
        "valid_conditions": ["cross_market_divergence", "cross_side_divergence"],
        "signal_values": {
            "long": "bullish_spot_vs_futures_bullish_spot_vs_perp",
            "short": "bearish_spot_vs_futures_bearish_spot_vs_perp",
        },
    },
    "EMA_RIBBON_PULLBACK": {
        "description": "4-EMA ribbon alignment with pullback entry in strong trends. Has built-in ADX + RSI filters.",
        "params": {
            "ema_periods": "list of 4 ints (default [8,13,21,34])",
            "rsi_period": "int (default 14)",
            "rsi_low": "int (default 35)",
            "rsi_high": "int (default 65)",
            "adx_period": "int (default 14)",
            "adx_threshold": "int (default 25)",
            "min_spread_pct": "float (default 0.001)",
        },
        "valid_conditions": ["pullback"],
        "signal_values": {
            "long": "bullish_ribbon_pullback",
            "short": "bearish_ribbon_pullback",
        },
    },
    "MARKET_STRUCTURE": {
        "description": "SMC: Break of Structure (BOS) and Change of Character (CHoCH)",
        "params": {"swing_lookback": "int (default 5)"},
        "valid_conditions": ["structure_break"],
        "signal_values": {
            "long": "bullish_bos or bullish_choch",
            "short": "bearish_bos or bearish_choch",
        },
    },
    "FAIR_VALUE_GAP": {
        "description": "SMC: Fair Value Gap detection and fill signals",
        "params": {"min_gap_pct": "float (default 0.0005)", "max_fvg_age": "int (default 20)"},
        "valid_conditions": ["fvg_fill"],
        "signal_values": {
            "long": "bullish_fvg",
            "short": "bearish_fvg",
        },
    },
    "ORDER_BLOCK": {
        "description": "SMC: Order Block detection and retest signals",
        "params": {
            "impulse_mult": "float (default 2.0)",
            "ob_lookback": "int (default 3)",
            "max_ob_age": "int (default 30)",
            "avg_range_period": "int (default 14)",
        },
        "valid_conditions": ["ob_retest"],
        "signal_values": {
            "long": "bullish_ob",
            "short": "bearish_ob",
        },
    },
    "LIQUIDITY_SWEEP": {
        "description": "SMC: Liquidity sweep (stop hunt) detection",
        "params": {
            "swing_lookback": "int (default 5)",
            "sweep_buffer_pct": "float (default 0.0002)",
            "max_sweep_levels": "int (default 10)",
        },
        "valid_conditions": ["sweep"],
        "signal_values": {
            "long": "bullish_sweep",
            "short": "bearish_sweep",
        },
    },
    "SMC_CONFLUENCE": {
        "description": "SMC: Combined signal requiring 2+ aligned SMC concepts",
        "params": {
            "min_confluence": "int (default 2)",
            "choch_weight": "int (default 2)",
        },
        "valid_conditions": ["confluence"],
        "signal_values": {
            "long": "bullish_confluence",
            "short": "bearish_confluence",
        },
    },
}


def _get_client():
    """Create Anthropic API client."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
    return anthropic.Anthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def evolve_strategies():
    """Main entry point called by Celery task.

    Orchestrates the full strategy evolution pipeline:
    audit -> research -> generate -> backtest -> promote/retire.
    """
    logger.info("=" * 70)
    logger.info("STRATEGY EVOLUTION ENGINE -- Starting run at %s", timezone.now())
    logger.info("=" * 70)

    try:
        # Step 1: Audit current strategies
        audit = _audit_current_strategies()
        logger.info(
            "Audit complete: %d active strategies, %d total custom strategies",
            audit["active_count"],
            audit["total_custom_count"],
        )

        # Step 2: Research new strategy ideas
        concepts = _research_strategies(audit)
        logger.info("Research complete: %d strategy concepts generated", len(concepts))

        # Step 3-4: Generate definitions and backtest each
        promoted = 0
        for i, concept in enumerate(concepts):
            logger.info(
                "----- Candidate %d/%d: %s -----",
                i + 1, len(concepts), concept.get("name", "unnamed"),
            )

            try:
                definition = _generate_strategy_definition(concept)
                if definition is None:
                    logger.warning("Skipping candidate %d: definition generation failed", i + 1)
                    continue

                logger.info(
                    "Definition generated: %d indicators, %d long rules, %d short rules, pairs=%s",
                    len(definition.get("indicators", [])),
                    len(definition.get("entry_rules", {}).get("long", [])),
                    len(definition.get("entry_rules", {}).get("short", [])),
                    definition.get("pairs", []),
                )

                # Step 4: Backtest
                result = _backtest_candidate(definition)
                if result is None:
                    logger.warning("Skipping candidate %d: backtest failed", i + 1)
                    continue

                logger.info(
                    "Backtest result: trades=%d, win_rate=%.3f, pnl=%.6f, pf=%s",
                    result["total_trades"],
                    result["win_rate"],
                    result["total_pnl"],
                    result.get("profit_factor"),
                )

                # Step 5: Promote if it meets thresholds
                candidate_tf = definition.get("timeframe", "M15")
                if _meets_promotion_thresholds(result, timeframe=candidate_tf):
                    _promote_strategy(
                        name=concept.get("name", f"Evolved Strategy {timezone.now().strftime('%Y%m%d_%H%M')}"),
                        definition=definition,
                        backtest_result=result,
                        description=concept.get("description", ""),
                    )
                    promoted += 1
                    logger.info("PROMOTED: %s", concept.get("name"))
                else:
                    logger.info(
                        "NOT promoted (thresholds not met): trades=%d (need>=%d), "
                        "wr=%.3f (need>=%.3f), pnl=%.6f (need>%.1f), pf=%s (need>=%.1f)",
                        result["total_trades"], MIN_TOTAL_TRADES,
                        result["win_rate"], MIN_WIN_RATE,
                        result["total_pnl"], MIN_TOTAL_PNL,
                        result.get("profit_factor"), MIN_PROFIT_FACTOR,
                    )

            except Exception:
                logger.error(
                    "Error processing candidate %d (%s):\n%s",
                    i + 1, concept.get("name", "unnamed"), traceback.format_exc(),
                )

        # Step 6: Retire underperformers
        retired = _retire_underperformers()

        logger.info("=" * 70)
        logger.info(
            "STRATEGY EVOLUTION ENGINE -- Run complete. Promoted: %d, Retired: %d",
            promoted, retired,
        )
        logger.info("=" * 70)

        return {
            "promoted": promoted,
            "retired": retired,
            "candidates_evaluated": len(concepts),
            "timestamp": timezone.now().isoformat(),
        }

    except Exception:
        logger.error("Strategy Evolution Engine FATAL ERROR:\n%s", traceback.format_exc())
        raise


# ---------------------------------------------------------------------------
# Step 1: Audit
# ---------------------------------------------------------------------------

def _audit_current_strategies():
    """Analyze performance of all active strategies.

    Returns dict with: active strategies, their recent P&L, win rates,
    gaps in coverage (pairs/timeframes not yet covered).
    """
    logger.info("Auditing current strategies...")

    active_configs = StrategyConfig.objects.filter(is_active=True)
    all_custom = CustomStrategy.objects.filter(domain=DOMAIN)

    strategy_summaries = []
    covered_pairs = set()
    covered_timeframes = set()
    covered_indicators = set()

    for config in active_configs:
        summary = {
            "name": config.name,
            "is_active": config.is_active,
            "priority": config.priority,
        }

        # Get recent backtest results
        recent_backtests = BacktestResult.objects.filter(
            strategy=config
        ).order_by("-run_time")[:5]

        if recent_backtests.exists():
            latest = recent_backtests.first()
            summary["latest_win_rate"] = latest.win_rate
            summary["latest_pnl"] = latest.total_pnl
            summary["latest_trades"] = latest.total_trades
            summary["latest_profit_factor"] = latest.profit_factor
            summary["latest_passed"] = latest.passed
            summary["consecutive_failures"] = 0

            for bt in recent_backtests:
                if not bt.passed:
                    summary["consecutive_failures"] += 1
                else:
                    break
        else:
            summary["latest_win_rate"] = None
            summary["latest_pnl"] = None
            summary["latest_trades"] = None
            summary["latest_profit_factor"] = None
            summary["latest_passed"] = None
            summary["consecutive_failures"] = 0

        # Extract pairs, timeframe, indicators from linked CustomStrategy
        try:
            custom = config.custom_definition
            defn = custom.definition or {}
            for pair in defn.get("pairs", []):
                covered_pairs.add(pair)
            tf = defn.get("timeframe")
            if tf:
                covered_timeframes.add(tf)
            for ind in defn.get("indicators", []):
                covered_indicators.add(ind.get("type", ""))
            summary["definition_summary"] = {
                "pairs": defn.get("pairs", []),
                "timeframe": tf,
                "indicators": [ind.get("type") for ind in defn.get("indicators", [])],
            }
        except CustomStrategy.DoesNotExist:
            summary["definition_summary"] = None

        strategy_summaries.append(summary)

    # Identify gaps
    uncovered_pairs = [p for p in FOREX_PAIRS if p not in covered_pairs]
    uncovered_timeframes = [t for t in VALID_TIMEFRAMES if t not in covered_timeframes]
    unused_indicators = [
        ind for ind in AVAILABLE_INDICATORS
        if ind not in covered_indicators and ind != "SWING_DETECTOR"
    ]

    audit = {
        "active_count": active_configs.count(),
        "total_custom_count": all_custom.count(),
        "strategy_summaries": strategy_summaries,
        "covered_pairs": sorted(covered_pairs),
        "uncovered_pairs": uncovered_pairs,
        "covered_timeframes": sorted(covered_timeframes),
        "uncovered_timeframes": uncovered_timeframes,
        "covered_indicators": sorted(covered_indicators),
        "unused_indicators": unused_indicators,
    }

    logger.info("Audit: covered pairs=%s, uncovered=%s", audit["covered_pairs"], audit["uncovered_pairs"])
    logger.info("Audit: unused indicators=%s", audit["unused_indicators"])
    logger.info("Audit: strategy summaries=%s", json.dumps(strategy_summaries, indent=2, default=str))

    return audit


# ---------------------------------------------------------------------------
# Step 2: Research
# ---------------------------------------------------------------------------

def _research_strategies(audit_context):
    """Use Claude to brainstorm new strategy ideas based on the audit.

    Uses claude-sonnet-4-6 for strong reasoning about strategy design.

    Returns list of strategy concepts (dicts with name, description,
    suggested_indicators, suggested_timeframe, suggested_pairs).
    """
    logger.info("Researching new strategy ideas with %s...", RESEARCH_MODEL)

    indicator_docs_str = json.dumps(INDICATOR_DOCS, indent=2)

    system_prompt = """You are an expert quantitative forex strategy researcher.
Your job is to design profitable forex trading strategies that can be implemented
using the available indicators in our backtesting system.

Key constraints:
- You MUST only use indicators from the provided INDICATOR_REGISTRY
- Strategies must have clear, mechanical entry rules (no discretion)
- Focus on strategies with good risk/reward ratios
- Each strategy should have both long AND short entry rules
- Exit rules should use ATR-based stops (our system supports this natively)
- Be creative but realistic -- avoid overfitting to specific market conditions
- Consider combining multiple indicators for confluence-based strategies
- Prefer strategies that would generate at least 50+ trades over 60 days of data

You are designing strategies for FOREX pairs: EURUSD, GBPUSD, USDJPY, AUDUSD, NZDUSD, USDCAD, USDCHF, EURGBP.
"""

    user_prompt = f"""Based on the following audit of our current strategy portfolio, design {MAX_STRATEGIES_TO_GENERATE} new forex trading strategy concepts.

## Current Strategy Audit
{json.dumps(audit_context, indent=2, default=str)}

## Available Indicators and Their Documentation
{indicator_docs_str}

## Available Forex Pairs
{json.dumps(FOREX_PAIRS)}

## Requirements
1. Focus on GAPS -- uncovered pairs, unused indicators, missing timeframes
2. Each strategy should be distinct from existing ones
3. Prefer combining 2-3 indicators for better signal quality
4. For signal-based indicators, entry rules must use the correct condition type and exact signal value strings
5. For numeric indicators (RSI, ATR), use numeric comparison conditions (gt, lt, gte, lte, eq)
6. Include optimal parameter suggestions
7. Consider multiple timeframes (M5, M15, H1, H4)

Respond with a JSON array of strategy concepts. Each concept should have:
- "name": A descriptive strategy name (max 60 chars)
- "description": What the strategy does and why it should work (2-3 sentences)
- "suggested_indicators": List of indicator types to use
- "suggested_timeframe": Which timeframe to use
- "suggested_pairs": Which pairs to trade (3-5 pairs)
- "rationale": Why this combination should be profitable

Return ONLY the JSON array, no other text."""

    try:
        client = _get_client()
        response = client.messages.create(
            model=RESEARCH_MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = response.content[0].text.strip()
        logger.info("Research response length: %d chars", len(response_text))

        # Parse JSON from the response -- handle markdown code fences
        json_text = response_text
        if "```json" in json_text:
            json_text = json_text.split("```json")[1].split("```")[0].strip()
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0].strip()

        concepts = json.loads(json_text)

        if not isinstance(concepts, list):
            logger.error("Research response was not a JSON array: %s", type(concepts))
            return []

        # Limit to max
        concepts = concepts[:MAX_STRATEGIES_TO_GENERATE]

        for concept in concepts:
            logger.info(
                "Research concept: '%s' -- indicators=%s, tf=%s, pairs=%s",
                concept.get("name"),
                concept.get("suggested_indicators"),
                concept.get("suggested_timeframe"),
                concept.get("suggested_pairs"),
            )

        return concepts

    except json.JSONDecodeError as e:
        logger.error("Failed to parse research response as JSON: %s\nRaw: %s", e, response_text[:500])
        return []
    except Exception:
        logger.error("Research step failed:\n%s", traceback.format_exc())
        return []


# ---------------------------------------------------------------------------
# Step 3: Generate strategy definition
# ---------------------------------------------------------------------------

def _generate_strategy_definition(concept):
    """Use Claude to convert a strategy concept into a valid strategy definition JSON.

    Uses claude-haiku-4-5-20251001 for fast structured output.

    Must only use indicators that exist in INDICATOR_REGISTRY.
    Validates the output before returning.
    """
    logger.info("Generating strategy definition for: %s", concept.get("name"))

    indicator_docs_str = json.dumps(INDICATOR_DOCS, indent=2)

    system_prompt = f"""You are a quantitative strategy definition generator.
Convert strategy concepts into exact JSON definitions that can be used by our backtesting engine.

CRITICAL RULES:
1. Only use indicators from this exact list: {json.dumps(AVAILABLE_INDICATORS)}
2. Only use conditions from this exact list: {json.dumps(AVAILABLE_CONDITIONS)}
3. For numeric indicators (RSI, ATR, CVD_RAW), use NUMERIC conditions: {json.dumps(NUMERIC_CONDITIONS)}
4. For signal-based indicators, use their specific condition type (see docs below)
5. Signal values must be EXACT strings as documented (e.g., 'bullish_sweep', not 'sweep_bullish')
6. Every strategy MUST have both 'long' and 'short' entry rules
7. Exit rules should use ATR_BASED type with atr_period, sl_multiplier, tp_multiplier
8. The 'pairs' array must only contain valid forex pairs
9. The 'timeframe' must be one of: {json.dumps(VALID_TIMEFRAMES)}

## Indicator Documentation
{indicator_docs_str}
"""

    example_definition = json.dumps({
        "pairs": ["EURUSD", "GBPUSD", "USDJPY"],
        "timeframe": "M15",
        "indicators": [
            {"type": "RSI", "params": {"period": 14}},
            {"type": "BOLLINGER_BANDS", "params": {"window": 20, "num_std_dev": 2}},
        ],
        "entry_rules": {
            "long": [
                {"indicator": "RSI", "condition": "lt", "value": 30},
                {"indicator": "BOLLINGER_BANDS", "condition": "divergence", "value": "bottom"},
            ],
            "short": [
                {"indicator": "RSI", "condition": "gt", "value": 70},
                {"indicator": "BOLLINGER_BANDS", "condition": "divergence", "value": "top"},
            ],
        },
        "exit_rules": {
            "type": "ATR_BASED",
            "params": {
                "atr_period": 14,
                "sl_multiplier": 1.5,
                "tp_multiplier": 2.5,
            },
        },
    }, indent=2)

    user_prompt = f"""Convert this strategy concept into a valid JSON definition:

## Strategy Concept
Name: {concept.get('name', 'unnamed')}
Description: {concept.get('description', '')}
Suggested Indicators: {json.dumps(concept.get('suggested_indicators', []))}
Suggested Timeframe: {concept.get('suggested_timeframe', 'M15')}
Suggested Pairs: {json.dumps(concept.get('suggested_pairs', FOREX_PAIRS[:4]))}
Rationale: {concept.get('rationale', '')}

## Example of a valid definition
{example_definition}

## Important notes on condition matching
- For signal-based indicators, the backtester checks: isinstance(actual_value, str) and target_value in actual_value
- So the 'value' in entry rules must be a SUBSTRING that appears in the signal string
- For EMA_CROSSOVER: condition='divergence', value='bull_cross' for long, 'bear_cross' for short
- For BOLLINGER_BANDS: condition='divergence', value='bottom' for long, 'top' for short
- For CVD: condition='divergence', value='bullish' for long, 'bearish' for short
- For MARKET_STRUCTURE: condition='structure_break', value='bullish' for long, 'bearish' for short
- For FAIR_VALUE_GAP: condition='fvg_fill', value='bullish' for long, 'bearish' for short
- For ORDER_BLOCK: condition='ob_retest', value='bullish' for long, 'bearish' for short
- For LIQUIDITY_SWEEP: condition='sweep', value='bullish' for long, 'bearish' for short
- For SMC_CONFLUENCE: condition='confluence', value='bullish' for long, 'bearish' for short
- For EMA_RIBBON_PULLBACK: condition='pullback', value='bullish' for long, 'bearish' for short
- For CVD_LEADING: condition='leading_divergence', value='bullish' for long, 'bearish' for short
- For CVD_EXTREMES: condition='extreme_divergence', value='bullish' for long, 'bearish' for short
- For CVD_MTF: condition='mtf_divergence', value='bullish' for long, 'bearish' for short

Return ONLY the JSON definition object, no other text."""

    try:
        client = _get_client()
        response = client.messages.create(
            model=GENERATION_MODEL,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = response.content[0].text.strip()

        # Parse JSON
        json_text = response_text
        if "```json" in json_text:
            json_text = json_text.split("```json")[1].split("```")[0].strip()
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0].strip()

        definition = json.loads(json_text)

        # Validate the definition
        validated = _validate_definition(definition)
        if validated is None:
            logger.warning("Definition validation failed for: %s", concept.get("name"))
            return None

        logger.info("Definition generated and validated successfully for: %s", concept.get("name"))
        return validated

    except json.JSONDecodeError as e:
        logger.error("Failed to parse definition JSON: %s\nRaw: %s", e, response_text[:500])
        return None
    except Exception:
        logger.error("Definition generation failed:\n%s", traceback.format_exc())
        return None


def _validate_definition(definition):
    """Validate and sanitize a strategy definition.

    Checks:
    - All indicators exist in INDICATOR_REGISTRY
    - All conditions exist in CONDITION_OPS
    - Required fields are present
    - Pairs are valid forex pairs
    - Timeframe is valid

    Returns sanitized definition or None if invalid.
    """
    errors = []

    # Check required top-level fields
    if not isinstance(definition, dict):
        logger.error("Definition is not a dict")
        return None

    pairs = definition.get("pairs", [])
    if not pairs:
        errors.append("Missing 'pairs'")
    else:
        valid_pairs = [p for p in pairs if p in FOREX_PAIRS]
        if not valid_pairs:
            errors.append(f"No valid forex pairs in {pairs}")
        definition["pairs"] = valid_pairs

    timeframe = definition.get("timeframe", "M15")
    if timeframe not in VALID_TIMEFRAMES:
        logger.warning("Invalid timeframe '%s', defaulting to M15", timeframe)
        definition["timeframe"] = "M15"

    indicators = definition.get("indicators", [])
    if not indicators:
        errors.append("Missing 'indicators'")
    else:
        valid_indicators = []
        for ind in indicators:
            ind_type = ind.get("type")
            if ind_type not in INDICATOR_REGISTRY:
                logger.warning("Removing unknown indicator: %s", ind_type)
                continue
            valid_indicators.append(ind)
        if not valid_indicators:
            errors.append("No valid indicators after filtering")
        definition["indicators"] = valid_indicators

    entry_rules = definition.get("entry_rules", {})
    long_rules = entry_rules.get("long", [])
    short_rules = entry_rules.get("short", [])

    if not long_rules and not short_rules:
        errors.append("No entry rules (need at least long or short)")

    # Validate each rule
    indicator_types = {ind.get("type") for ind in definition.get("indicators", [])}

    for side, rules in [("long", long_rules), ("short", short_rules)]:
        valid_rules = []
        for rule in rules:
            ind = rule.get("indicator")
            cond = rule.get("condition")
            val = rule.get("value")

            if ind not in indicator_types:
                logger.warning(
                    "Rule references indicator '%s' not in declared indicators %s -- skipping",
                    ind, indicator_types,
                )
                continue
            if cond not in CONDITION_OPS:
                logger.warning("Unknown condition '%s' -- skipping rule", cond)
                continue
            if val is None:
                logger.warning("Rule missing 'value' -- skipping")
                continue

            valid_rules.append({"indicator": ind, "condition": cond, "value": val})

        entry_rules[side] = valid_rules

    definition["entry_rules"] = entry_rules

    if not entry_rules.get("long") and not entry_rules.get("short"):
        errors.append("No valid entry rules after filtering")

    # Validate exit rules -- default to ATR_BASED if missing
    exit_rules = definition.get("exit_rules", {})
    if not exit_rules or not exit_rules.get("params"):
        definition["exit_rules"] = {
            "type": "ATR_BASED",
            "params": {
                "atr_period": 14,
                "sl_multiplier": 1.5,
                "tp_multiplier": 2.5,
            },
        }

    if errors:
        logger.error("Definition validation errors: %s", errors)
        return None

    return definition


# ---------------------------------------------------------------------------
# Step 4: Backtest
# ---------------------------------------------------------------------------

def _backtest_candidate(definition):
    """Run GenericBacktester on a candidate strategy definition.

    Returns backtest results dict or None on failure.
    """
    logger.info(
        "Backtesting candidate: pairs=%s, tf=%s, indicators=%s",
        definition.get("pairs"),
        definition.get("timeframe"),
        [ind.get("type") for ind in definition.get("indicators", [])],
    )

    try:
        backtester = GenericBacktester(definition)
        result = backtester.run()

        logger.info(
            "Backtest complete: %d trades, %.3f win rate, %.6f PnL, pf=%s",
            result["total_trades"],
            result["win_rate"],
            result["total_pnl"],
            result.get("profit_factor"),
        )

        return result

    except Exception:
        logger.error("Backtest failed:\n%s", traceback.format_exc())
        return None


def _meets_promotion_thresholds(result, timeframe=None):
    """Check if backtest results meet promotion thresholds.

    Higher timeframes (H1, H4, D1) produce fewer trades in 60-day windows,
    so we adjust the minimum trade count accordingly.
    """
    # Timeframe-aware trade minimums
    tf_min_trades = {
        'M5': 50, 'M15': 40, 'M30': 30, 'H1': 15, 'H4': 8, 'D1': 5
    }
    min_trades = tf_min_trades.get(timeframe, MIN_TOTAL_TRADES)

    if result["total_trades"] < min_trades:
        return False
    if result["win_rate"] < MIN_WIN_RATE:
        return False
    if result["total_pnl"] <= MIN_TOTAL_PNL:
        return False
    pf = result.get("profit_factor")
    if pf is None or pf < MIN_PROFIT_FACTOR:
        return False
    return True


# ---------------------------------------------------------------------------
# Step 5: Promote
# ---------------------------------------------------------------------------

def _promote_strategy(name, definition, backtest_result, description=""):
    """Create CustomStrategy + StrategyConfig + BacktestResult records.

    Sets is_active=True since the strategy passed all promotion thresholds.
    """
    logger.info("Promoting strategy: %s", name)

    # Ensure unique name -- append timestamp if collision
    base_name = name[:50]
    config_name = base_name
    suffix = 0
    while StrategyConfig.objects.filter(name=config_name).exists():
        suffix += 1
        config_name = f"{base_name[:45]}_{suffix}"

    try:
        with transaction.atomic():
            # Create StrategyConfig
            config = StrategyConfig.objects.create(
                name=config_name,
                is_active=True,
                description=description,
                last_activated=timezone.now(),
                priority=20,  # Lower priority than manually configured strategies
                max_positions=2,
                capital_allocation_pct=0.15,  # Conservative allocation for auto-generated
            )

            # Create CustomStrategy linked to StrategyConfig
            custom = CustomStrategy.objects.create(
                name=name[:100],
                description=description,
                definition=definition,
                domain=DOMAIN,
                strategy_config=config,
            )

            # Store backtest result
            bt = BacktestResult.objects.create(
                strategy=config,
                period_days=backtest_result.get("period_days", 60),
                total_trades=backtest_result["total_trades"],
                winning_trades=backtest_result["winning_trades"],
                losing_trades=backtest_result["losing_trades"],
                win_rate=backtest_result["win_rate"],
                total_pnl=backtest_result["total_pnl"],
                profit_factor=backtest_result.get("profit_factor"),
                avg_win=backtest_result.get("avg_win"),
                avg_loss=backtest_result.get("avg_loss"),
                passed=True,
                data_source=backtest_result.get("data_source", "YAHOO"),
                trades=backtest_result.get("trades", []),
                equity_curve=backtest_result.get("equity_curve", []),
                symbol_breakdown=backtest_result.get("symbol_breakdown", {}),
            )

            logger.info(
                "Promotion complete: StrategyConfig=%d, CustomStrategy=%d, BacktestResult=%d",
                config.pk, custom.pk, bt.pk,
            )

            return config

    except Exception:
        logger.error("Promotion failed:\n%s", traceback.format_exc())
        return None


# ---------------------------------------------------------------------------
# Step 6: Retire underperformers
# ---------------------------------------------------------------------------

def _retire_underperformers():
    """Deactivate strategies with poor live + backtest performance.

    Criteria for retirement:
    - Consecutive failed backtests >= MAX_CONSECUTIVE_FAILED_BACKTESTS
    - OR: total_pnl negative AND win_rate < 0.40 on latest backtest
    - Only retires auto-evolved strategies (priority >= 20) to avoid
      deactivating manually configured strategies.

    Returns count of retired strategies.
    """
    logger.info("Checking for underperforming strategies to retire...")

    retired_count = 0

    # Only consider auto-evolved strategies (priority >= 20 as set in _promote_strategy)
    active_configs = StrategyConfig.objects.filter(
        is_active=True,
        priority__gte=20,
    )

    for config in active_configs:
        try:
            recent_backtests = BacktestResult.objects.filter(
                strategy=config
            ).order_by("-run_time")[:MAX_CONSECUTIVE_FAILED_BACKTESTS]

            if not recent_backtests.exists():
                continue

            # Check consecutive failures
            consecutive_failures = 0
            for bt in recent_backtests:
                if not bt.passed:
                    consecutive_failures += 1
                else:
                    break

            latest = recent_backtests.first()

            should_retire = False
            reason = ""

            if consecutive_failures >= MAX_CONSECUTIVE_FAILED_BACKTESTS:
                should_retire = True
                reason = f"{consecutive_failures} consecutive failed backtests"

            elif latest.total_pnl < 0 and latest.win_rate < 0.40:
                should_retire = True
                reason = f"Negative PnL ({latest.total_pnl:.6f}) with low win rate ({latest.win_rate:.3f})"

            if should_retire:
                config.is_active = False
                config.save(update_fields=["is_active"])
                retired_count += 1
                logger.info(
                    "RETIRED: '%s' (config_id=%d) -- Reason: %s",
                    config.name, config.pk, reason,
                )

        except Exception:
            logger.error(
                "Error checking retirement for '%s':\n%s",
                config.name, traceback.format_exc(),
            )

    logger.info("Retirement check complete: %d strategies retired", retired_count)
    return retired_count
