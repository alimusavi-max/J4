"""Strategy layer for repricer target-price decision."""
from dataclasses import dataclass


@dataclass
class StrategyInput:
    competitor_price: int
    current_price: int
    reference_price: int
    step_price: int
    min_price: int
    max_price: int
    buy_box_price: int


class AggressiveStrategy:
    def decide(self, d: StrategyInput) -> int:
        return d.competitor_price - d.step_price


class ConservativeStrategy:
    def decide(self, d: StrategyInput) -> int | None:
        if d.competitor_price - d.current_price > d.step_price * 3:
            return d.competitor_price - d.step_price
        return None
