from dataclasses import dataclass
from typing import Optional
from enum import Enum

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

@dataclass
class Order:
    """Represents a perpetual futures order"""
    size: float
    price: float
    side: OrderSide  # Ensure using OrderSide enum
    reduce_only: bool = False
    post_only: bool = True
    
    def __str__(self) -> str:
        return (
            f"Order({self.side.value} {self.size} @ {self.price:.2f} "
            f"{'reduce_only ' if self.reduce_only else ''}"
            f"{'post_only' if self.post_only else ''})"
        )

    @classmethod
    def from_string(cls, side: str, **kwargs) -> 'Order':
        """Create Order with string side value"""
        return cls(side=OrderSide(side.lower()), **kwargs)

@dataclass
class PerpMarketState:
    """Market state for perpetual futures trading"""
    asset: str
    best_bid: float
    best_ask: float
    mark_price: float
    position: float
    margin_summary: dict
    cross_margin_summary: dict
    all_positions: list
    
    @property
    def spread(self) -> float:
        """Calculate current bid-ask spread"""
        return (self.best_ask - self.best_bid) / self.best_bid if self.best_bid > 0 else 0
        
    @property
    def mid_price(self) -> float:
        """Calculate mid price"""
        return (self.best_bid + self.best_ask) / 2
        
    def __str__(self) -> str:
        return (
            f"PerpMarketState(asset={self.asset}, "
            f"mark=${self.mark_price:.4f}, "
            f"spread={self.spread:.4%}, "
            f"pos={self.position:.4f})"
        )

