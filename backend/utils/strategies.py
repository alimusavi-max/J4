"""Pricing strategies with adaptive memory for Digikala repricer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


BASE_DIR = Path(__file__).resolve().parent.parent
LEARNING_MEMORY_FILE = BASE_DIR / "learning_memory.json"


@dataclass
class StrategyInput:
    """Input payload for price decision making."""

    competitor_price: int
    current_price: int
    min_price: int
    max_price: int
    step: int
    is_buy_box_winner: bool
    alone_in_market: bool
    winner_info: Optional[Dict[str, Any]] = None


class AdaptiveMemory:
    """Persistent memory store that tracks learned gap per competitor seller."""

    def __init__(self, path: Path = LEARNING_MEMORY_FILE) -> None:
        self.path = path
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._cache = data
            except Exception:
                self._cache = {}
        self._loaded = True

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def get_competitor_state(self, competitor_seller_id: int) -> Dict[str, Any]:
        """Return known state for a competitor seller id."""
        self._load()
        return self._cache.get(str(competitor_seller_id), {}).copy()

    def record_result(self, competitor_seller_id: int, gap: int, won: bool) -> None:
        """Store the latest applied gap and whether it won buy-box."""
        self._load()
        self._cache[str(competitor_seller_id)] = {
            "last_gap": int(max(0, gap)),
            "last_result": "win" if won else "loss",
        }
        self._save()


class AdaptiveSniperStrategy:
    """Adaptive sniper strategy that learns per-competitor winning gap."""

    name = "adaptive_sniper"
    label = "Adaptive Sniper AI"
    description = "یادگیری فاصله قیمتی بهینه برای هر رقیب با حافظه تاریخی."

    def __init__(self, memory: Optional[AdaptiveMemory] = None) -> None:
        self.memory = memory or AdaptiveMemory()

    @staticmethod
    def _clamp(target: int, min_price: int, max_price: int) -> int:
        return max(min_price, min(max_price, target))

    @staticmethod
    def _initial_gap(step: int, item_votes: int) -> int:
        if item_votes >= 10000:
            return step * 3
        if item_votes >= 3000:
            return step * 2
        return step

    def decide(self, d: StrategyInput) -> Optional[int]:
        """Calculate target price based on current context and learned memory."""
        step = max(1, int(d.step))

        if d.is_buy_box_winner:
            if d.alone_in_market or d.competitor_price <= 0:
                return self._clamp(d.max_price, d.min_price, d.max_price)

            candidate = d.competitor_price - step
            if candidate <= d.current_price:
                return None
            return self._clamp(candidate, d.min_price, d.max_price)

        if d.competitor_price <= 0:
            return None

        winner_info = d.winner_info or {}
        competitor_seller_id = int(winner_info.get("seller_id") or 0)
        item_votes = int(winner_info.get("item_votes") or 0)

        state = self.memory.get_competitor_state(competitor_seller_id) if competitor_seller_id else {}
        last_gap = int(state.get("last_gap") or 0)
        last_result = state.get("last_result")

        if last_gap > 0:
            gap = last_gap if last_result == "win" else last_gap + step
        else:
            gap = self._initial_gap(step=step, item_votes=item_votes)

        target = d.competitor_price - gap
        target = self._clamp(target, d.min_price, d.max_price)
        if target == d.current_price:
            return None
        return target


ADAPTIVE_STRATEGY = AdaptiveSniperStrategy()

STRATEGIES: Dict[str, AdaptiveSniperStrategy] = {
    "adaptive_sniper": ADAPTIVE_STRATEGY,
    "smart": ADAPTIVE_STRATEGY,
    "aggressive": ADAPTIVE_STRATEGY,
    "conservative": ADAPTIVE_STRATEGY,
    "step_up": ADAPTIVE_STRATEGY,
}

STRATEGY_INFO = [
    {
        "key": "adaptive_sniper",
        "label": AdaptiveSniperStrategy.label,
        "desc": AdaptiveSniperStrategy.description,
    }
]


def get_strategy(name: str) -> AdaptiveSniperStrategy:
    """Get strategy instance by configured key with backward compatibility."""
    return STRATEGIES.get(name, ADAPTIVE_STRATEGY)
