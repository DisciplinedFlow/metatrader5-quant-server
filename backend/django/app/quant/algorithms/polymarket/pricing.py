import math
import logging

logger = logging.getLogger('app.polymarket')


def lmsr_price(q_yes, q_no, b):
    """LMSR price for YES outcome. p(yes) = e^(q_yes/b) / (e^(q_yes/b) + e^(q_no/b))"""
    exp_yes = math.exp(q_yes / b)
    exp_no = math.exp(q_no / b)
    return exp_yes / (exp_yes + exp_no)


def lmsr_cost(q_yes, q_no, b):
    """LMSR cost function: C = b * ln(e^(q_yes/b) + e^(q_no/b))"""
    return b * math.log(math.exp(q_yes / b) + math.exp(q_no / b))


def bayesian_update(alpha, beta, observation, weight=1.0):
    """Update Beta distribution with new observation.
    observation: market price observation (0-1)
    Returns (new_alpha, new_beta)
    """
    new_alpha = alpha + observation * weight
    new_beta = beta + (1 - observation) * weight
    return new_alpha, new_beta


def beta_mean(alpha, beta):
    """Mean of Beta distribution."""
    return alpha / (alpha + beta)


def compute_ev(model_probability, market_price):
    """Expected value edge: model prob - market price.
    Positive EV means market underprices YES.
    """
    return model_probability - market_price


def compute_ev_no(model_probability, market_price):
    """EV for NO side: (1 - model_prob) - (1 - market_price) = market_price - model_prob"""
    return market_price - model_probability
