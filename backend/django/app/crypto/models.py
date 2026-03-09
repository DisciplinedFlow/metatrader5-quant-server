from django.db import models


class CryptoPosition(models.Model):
    class Side(models.TextChoices):
        LONG = 'LONG', 'Long'
        SHORT = 'SHORT', 'Short'

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        CLOSED = 'CLOSED', 'Closed'

    class CloseReason(models.TextChoices):
        SIGNAL_REVERSAL = 'SIGNAL_REVERSAL', 'Signal Reversal'
        STOP_LOSS = 'STOP_LOSS', 'Stop Loss'
        TAKE_PROFIT = 'TAKE_PROFIT', 'Take Profit'
        PROFIT_PROTECTION = 'PROFIT_PROTECTION', 'Profit Protection'
        TIME_EXIT = 'TIME_EXIT', 'Time Exit'
        MANUAL = 'MANUAL', 'Manual'

    symbol = models.CharField(max_length=20)
    side = models.CharField(max_length=5, choices=Side.choices)
    entry_price = models.FloatField()
    size = models.FloatField()
    leverage = models.IntegerField(default=1)
    entry_signal = models.CharField(max_length=50, blank=True)
    stop_loss = models.FloatField(null=True, blank=True)
    take_profit = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=6, choices=Status.choices, default='OPEN')
    close_price = models.FloatField(null=True, blank=True)
    pnl_usd = models.FloatField(null=True, blank=True)
    close_reason = models.CharField(max_length=20, choices=CloseReason.choices, null=True, blank=True)
    peak_profit_usd = models.FloatField(null=True, blank=True, help_text="Peak unrealized PnL in USD, tracked for profit protection")
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-opened_at']

    def __str__(self):
        return f"{self.side} {self.symbol} {self.size} @ {self.entry_price}"


class CryptoTrade(models.Model):
    class Side(models.TextChoices):
        BUY = 'BUY', 'Buy'
        SELL = 'SELL', 'Sell'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        FILLED = 'FILLED', 'Filled'
        FAILED = 'FAILED', 'Failed'

    position = models.ForeignKey(CryptoPosition, on_delete=models.CASCADE, related_name='trades')
    order_id = models.CharField(max_length=100)
    side = models.CharField(max_length=4, choices=Side.choices)
    price = models.FloatField()
    size = models.FloatField()
    fee = models.FloatField(default=0.0)
    status = models.CharField(max_length=7, choices=Status.choices, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.side} {self.size} {self.position.symbol} @ {self.price}"


class CryptoBacktestResult(models.Model):
    run_time = models.DateTimeField(auto_now_add=True)
    symbol = models.CharField(max_length=20, default='BTC')
    strategy_name = models.CharField(max_length=50, default='momentum')
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
    capital_usd = models.FloatField(default=1000)
    trades = models.JSONField(default=list, blank=True)
    equity_curve = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-run_time']

    def __str__(self):
        return f"CryptoBacktest {self.symbol} @ {self.run_time} - {'PASS' if self.passed else 'FAIL'}"
