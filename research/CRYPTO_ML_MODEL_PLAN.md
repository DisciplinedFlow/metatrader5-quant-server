# Crypto ML Model Plan — Mar 17, 2026

## Model Choice: Shallow XGBoost Ensemble

**Winner: XGBoost** (84.58% directional accuracy vs LSTM's 50.45% in head-to-head crypto tests)

For ~100 trades, use:
```python
XGBClassifier(
    n_estimators=100,
    max_depth=2,          # SHALLOW — prevents overfitting on small data
    learning_rate=0.01,   # LOW — regularization
    subsample=0.7,
    colsample_bytree=0.7,
    min_child_weight=5,   # HIGH — regularization
    reg_alpha=1.0,        # L1
    reg_lambda=2.0,       # L2
    scale_pos_weight=neg/pos_ratio,
)
```

Ensemble with LogisticRegression(C=0.1, L1) as sanity check. Only trade when ensemble confidence > 0.6.

## Feature Set (8-10 max for ~100 trades)

### Price-based (3)
- returns_1bar, returns_5bar
- ema_8_21_ratio

### Momentum (3)
- rsi_2 (our primary indicator)
- adx_14
- macd_histogram

### Volatility (2)
- bb_percent_b
- atr_14_normalized

### Context (2)
- hour_sin, hour_cos (cyclical time encoding)
- session_multiplier (our session sizing value)

## Training Pipeline
1. Walk-forward expanding window (NEVER shuffle time-series)
2. Normalize using ONLY training window statistics
3. SHAP for feature importance
4. Class weights for imbalance (not SMOTE on <200 trades)
5. Retrain weekly or on HMM regime shift
6. Supplement: convert ~100 trades → thousands of bar-level predictions

## Realistic Expectations
| Metric | Target | Overfit Warning |
|--------|--------|----------------|
| Direction accuracy | 53-58% | >65% |
| Win rate | 45-55% | >65% |
| Profit factor | 1.1-1.8 | >2.5 |
| Sharpe | 0.5-1.5 | >2.5 |

**55% accuracy with 1:2 R:R = profitable system**

## What NOT To Do
- Deep trees (max_depth > 3) with < 500 samples
- LSTM/GRU alone (50% accuracy on crypto)
- RL (needs tens of thousands of episodes)
- SMOTE on < 200 samples
- Normalize before train/test split
- Shuffle time-series data
- Chase 90%+ accuracy claims

## Implementation Priority
1. Collect 200+ trades (current: 99, need ~2 more days)
2. Build feature extractor from Neo4j trade data
3. Train XGBoost + LR ensemble with walk-forward
4. Integrate as ML meta-filter in Lighter entry strategies
5. Auto-retrain on regime shift or weekly

## Sources
30+ papers — see full research output.
