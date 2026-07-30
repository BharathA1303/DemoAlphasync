"""
AlphaSync ZeroLoss Strategy Module.

A confidence-gated, break-even-protected trading strategy that produces
exactly two outcomes on every trade: PROFIT or NO PROFIT / NO LOSS.

Components:
    confidence_engine  — Multi-indicator market confidence scorer (0–100)
    signal_generator   — Entry/exit signal logic with direction detection
    breakeven_manager  — Break-even stop-loss calculator including all costs
    controller         — Orchestrator that ties the pipeline together
"""

from strategies.zeroloss.confidence_engine import ConfidenceEngine
from strategies.zeroloss.signal_generator import ZeroLossSignalGenerator
from strategies.zeroloss.breakeven_manager import BreakevenManager
from strategies.zeroloss.controller import ZeroLossController
from strategies.zeroloss.manager import ZeroLossManager

__all__ = [
    "ConfidenceEngine",
    "ZeroLossSignalGenerator",
    "BreakevenManager",
    "ZeroLossController",
    "ZeroLossManager",
]
