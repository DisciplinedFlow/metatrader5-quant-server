from django.db import models


class PolyMarket(models.Model):
    condition_id = models.CharField(max_length=100, unique=True)
    question = models.TextField()
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    outcomes = models.JSONField(default=list)
    token_ids = models.JSONField(default=list)
    market_price = models.FloatField(default=0.5)
    model_probability = models.FloatField(null=True, blank=True)
    prior_alpha = models.FloatField(default=1.0)
    prior_beta = models.FloatField(default=1.0)
    last_synced = models.DateTimeField(auto_now=True)
    last_estimated = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.question[:80]


class PolyPosition(models.Model):
    class Side(models.TextChoices):
        YES = 'YES', 'Yes'
        NO = 'NO', 'No'

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        CLOSED = 'CLOSED', 'Closed'

    class CloseReason(models.TextChoices):
        EV_COLLAPSE = 'EV_COLLAPSE', 'EV Collapse'
        STOP_LOSS = 'STOP_LOSS', 'Stop Loss'
        RESOLVED = 'RESOLVED', 'Resolved'
        MANUAL = 'MANUAL', 'Manual'

    market = models.ForeignKey(PolyMarket, on_delete=models.CASCADE, related_name='positions')
    side = models.CharField(max_length=3, choices=Side.choices)
    entry_price = models.FloatField()
    shares = models.FloatField()
    cost_basis_usd = models.FloatField()
    entry_ev = models.FloatField()
    entry_model_prob = models.FloatField()
    kelly_fraction = models.FloatField()
    status = models.CharField(max_length=6, choices=Status.choices, default='OPEN')
    close_price = models.FloatField(null=True, blank=True)
    pnl_usd = models.FloatField(null=True, blank=True)
    close_reason = models.CharField(max_length=20, choices=CloseReason.choices, null=True, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-opened_at']

    def __str__(self):
        return f"{self.side} {self.market} @ {self.entry_price}"


class PolyTrade(models.Model):
    class Side(models.TextChoices):
        BUY = 'BUY', 'Buy'
        SELL = 'SELL', 'Sell'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        FILLED = 'FILLED', 'Filled'
        FAILED = 'FAILED', 'Failed'

    position = models.ForeignKey(PolyPosition, on_delete=models.CASCADE, related_name='trades')
    order_id = models.CharField(max_length=100)
    token_id = models.CharField(max_length=100)
    side = models.CharField(max_length=4, choices=Side.choices)
    price = models.FloatField()
    size = models.FloatField()
    status = models.CharField(max_length=7, choices=Status.choices, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.side} {self.size} @ {self.price}"


class PolyBacktestResult(models.Model):
    run_time = models.DateTimeField(auto_now_add=True)
    total_trades = models.IntegerField()
    winning_trades = models.IntegerField()
    losing_trades = models.IntegerField()
    win_rate = models.FloatField()
    total_pnl = models.FloatField()
    profit_factor = models.FloatField(null=True)
    avg_win = models.FloatField(null=True)
    avg_loss = models.FloatField(null=True)
    max_drawdown = models.FloatField(null=True)
    passed = models.BooleanField()
    capital_usd = models.FloatField(default=500)
    ev_threshold = models.FloatField(default=0.05)
    kelly_fraction = models.FloatField(default=0.15)
    trades = models.JSONField(default=list, blank=True)
    equity_curve = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-run_time']

    def __str__(self):
        return f"PolyBacktest @ {self.run_time} - {'PASS' if self.passed else 'FAIL'}"


class PolyProbabilityLog(models.Model):
    market = models.ForeignKey(PolyMarket, on_delete=models.CASCADE, related_name='probability_logs')
    market_price = models.FloatField()
    model_probability = models.FloatField()
    alpha = models.FloatField()
    beta = models.FloatField()
    ev = models.FloatField()
    reasoning = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.market} p={self.model_probability:.2f} ev={self.ev:.3f}"
