from django.db import models

class Trade(models.Model):
    TRADE_TYPE_CHOICES = [
        ('BUY', 'Buy'),
        ('SELL', 'Sell'),
    ]

    CLOSING_REASON_CHOICES = [
        ('TP', 'Take Profit'),
        ('SL', 'Stop Loss'),
        ('MANUAL', 'Manual'),
        ('LIQUIDATION', 'Liquidation'),
        ('OTHER', 'Other'),
    ]

    MARKET_TYPE_CHOICES = [
        ('FOREX', 'Forex'),
        ('CRYPTO', 'Crypto'),
        ('OTHER', 'Other'),
    ]

    TIMEFRAME_CHOICES = [
        ('1M', '1 Minute'),
        ('5M', '5 Minutes'),
        ('15M', '15 Minutes'),
        ('1H', '1 Hour'),
        ('4H', '4 Hours'),
        ('1D', '1 Day'),
    ]

    # Core trade fields
    transaction_broker_id = models.CharField(max_length=100)
    symbol = models.CharField(max_length=10)
    entry_time = models.DateTimeField()
    entry_price = models.FloatField()
    type = models.CharField(max_length=4, choices=TRADE_TYPE_CHOICES)
    position_size_usd = models.FloatField()
    capital = models.FloatField()
    leverage = models.FloatField(default=500)
    order_volume = models.FloatField(null=True, blank=True)
    liquidity_price = models.FloatField()
    break_even_price = models.FloatField()
    order_commission = models.FloatField()

    # Closing details
    close_time = models.DateTimeField(null=True, blank=True)
    close_price = models.FloatField(null=True, blank=True)
    pnl = models.FloatField(null=True, blank=True)
    pnl_excluding_commission = models.FloatField(null=True, blank=True)
    max_drawdown = models.FloatField(null=True, blank=True)
    max_profit = models.FloatField(null=True, blank=True)
    closing_reason = models.CharField(max_length=50, null=True, blank=True, choices=CLOSING_REASON_CHOICES)

    # Additional Info
    strategy = models.CharField(max_length=50)
    broker = models.CharField(max_length=50)
    market_type = models.CharField(max_length=50, choices=MARKET_TYPE_CHOICES)
    timeframe = models.CharField(max_length=50, choices=TIMEFRAME_CHOICES)

    # Adaptive trading engine fields
    strategy_config = models.ForeignKey(
        'StrategyConfig', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='trades',
    )
    breakeven_moved = models.BooleanField(default=False)
    partial_closed = models.BooleanField(default=False)
    partial_close_volume = models.FloatField(null=True, blank=True)
    partial_close_price = models.FloatField(null=True, blank=True)
    entry_timeframe = models.CharField(max_length=10, blank=True, default='M15')
    entry_atr = models.FloatField(null=True, blank=True)  # ATR at time of entry, for breakeven/trail calculations

    def __str__(self):
        return f"{self.type} {self.symbol} at {self.entry_price}"


class TradeClosePricesMutation(models.Model):
    trade = models.ForeignKey(Trade, on_delete=models.CASCADE, related_name='close_prices_mutations')
    mutation_time = models.DateTimeField(auto_now_add=True)
    mutation_price = models.FloatField(null=True, blank=True)
    new_tp_price = models.FloatField(null=True, blank=True)
    new_sl_price = models.FloatField(null=True, blank=True)
    pnl_at_new_tp_price = models.FloatField(null=True, blank=True)
    pnl_at_new_sl_price = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['mutation_time']
        verbose_name = "Trade Close Prices Mutation"
        verbose_name_plural = "Trade Close Prices Mutations"

    def __str__(self):
        return f"Mutation for {self.trade} at {self.mutation_time}"


class StrategyConfig(models.Model):
    REGIME_CHOICES = [
        ('', 'Any'),
        ('TRENDING_UP', 'Trending Up'),
        ('TRENDING_DOWN', 'Trending Down'),
        ('RANGING', 'Ranging'),
        ('VOLATILE', 'Volatile'),
    ]

    name = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    last_activated = models.DateTimeField(null=True, blank=True)
    priority = models.IntegerField(default=10)  # Lower = higher priority for pair conflict resolution
    max_positions = models.IntegerField(default=3)  # Per-strategy position cap
    capital_allocation_pct = models.FloatField(default=0.33)  # % of total capital
    regime_filter = models.CharField(
        max_length=20, blank=True, default='',
        choices=REGIME_CHOICES,
    )

    def __str__(self):
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"


class BacktestResult(models.Model):
    strategy = models.ForeignKey(
        StrategyConfig, on_delete=models.CASCADE, related_name='backtest_results'
    )
    run_time = models.DateTimeField(auto_now_add=True)
    period_days = models.IntegerField(default=7)
    total_trades = models.IntegerField()
    winning_trades = models.IntegerField()
    losing_trades = models.IntegerField()
    win_rate = models.FloatField()
    total_pnl = models.FloatField()
    profit_factor = models.FloatField(null=True)
    avg_win = models.FloatField(null=True)
    avg_loss = models.FloatField(null=True)
    passed = models.BooleanField()
    data_source = models.CharField(max_length=20, default='MT5')
    trades = models.JSONField(default=list, blank=True)
    equity_curve = models.JSONField(default=list, blank=True)
    symbol_breakdown = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-run_time']

    def __str__(self):
        return f"Backtest {self.strategy.name} @ {self.run_time} - {'PASS' if self.passed else 'FAIL'}"


class CustomStrategy(models.Model):
    DOMAIN_CHOICES = [
        ('FOREX', 'Forex'),
        ('CRYPTO', 'Crypto'),
        ('POLYMARKET', 'Polymarket'),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    definition = models.JSONField(default=dict)
    domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES, default='FOREX')
    strategy_config = models.OneToOneField(
        StrategyConfig, on_delete=models.CASCADE,
        related_name='custom_definition', null=True, blank=True
    )

    def __str__(self):
        return f"{self.name} ({self.domain})"


class PairLock(models.Model):
    """Prevents two strategies from opening positions on the same pair."""
    symbol = models.CharField(max_length=20, unique=True)
    strategy = models.ForeignKey(StrategyConfig, on_delete=models.CASCADE, related_name='pair_locks')
    ticket = models.BigIntegerField()  # MT5 position ticket
    locked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['symbol'])]

    def __str__(self):
        return f"{self.symbol} locked by {self.strategy.name} (ticket={self.ticket})"


class MarketRegime(models.Model):
    REGIME_CHOICES = [
        ('TRENDING_UP', 'Trending Up'),
        ('TRENDING_DOWN', 'Trending Down'),
        ('RANGING', 'Ranging'),
        ('VOLATILE', 'Volatile'),
        ('UNKNOWN', 'Unknown'),
    ]

    symbol = models.CharField(max_length=20)
    timeframe = models.CharField(max_length=10, default='H1')
    regime = models.CharField(max_length=20, choices=REGIME_CHOICES, default='UNKNOWN')
    adx = models.FloatField(default=0)
    bb_width = models.FloatField(default=0)
    atr_ratio = models.FloatField(default=0)
    confidence = models.FloatField(default=0)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('symbol', 'timeframe')

    def __str__(self):
        return f"{self.symbol} {self.timeframe}: {self.regime} (ADX={self.adx:.1f})"


class TradeFeature(models.Model):
    """Stores ML features extracted at trade entry and outcome after close.

    Each trade gets one TradeFeature row. At entry, features_json is populated.
    When the trade closes, actual_win is set and LLM training data is generated.
    """
    trade = models.OneToOneField(Trade, on_delete=models.CASCADE, related_name='ml_features')
    features_json = models.JSONField(default=dict)
    ml_score = models.FloatField(null=True, blank=True)  # Score at entry (0-1)
    ml_accepted = models.BooleanField(null=True, blank=True)  # Whether ML accepted the trade
    actual_win = models.BooleanField(null=True, blank=True)  # Set after trade closes
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['actual_win']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        outcome = 'WIN' if self.actual_win else 'LOSS' if self.actual_win is not None else 'OPEN'
        return f"Features for Trade #{self.trade_id} — {outcome}"


class MLModel(models.Model):
    """Tracks each trained ML model version and its performance metrics.

    The dashboard reads this to show learning curves, feature importance,
    and model progression over time.
    """
    version = models.IntegerField(unique=True)
    model_type = models.CharField(max_length=50)  # RandomForest or GradientBoosting
    trade_count = models.IntegerField()  # How many trades were used for training
    accuracy = models.FloatField()
    cv_accuracy = models.FloatField(default=0)  # Cross-validated accuracy
    cv_std = models.FloatField(default=0)  # CV standard deviation
    precision = models.FloatField(default=0)
    recall = models.FloatField(default=0)
    f1_score = models.FloatField(default=0)
    feature_importance = models.JSONField(default=dict)
    learning_curve = models.JSONField(default=list)  # [{trades: N, accuracy: X}, ...]
    win_rate_baseline = models.FloatField(default=0.5)  # Naive baseline WR
    model_path = models.CharField(max_length=200)  # Path to joblib file
    is_active = models.BooleanField(default=False)
    trained_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']

    def __str__(self):
        return f"ML v{self.version} ({self.model_type}) — {self.accuracy:.1%} acc, {self.trade_count} trades"