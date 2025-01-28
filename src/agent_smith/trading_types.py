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
    
    def __str__(self):
        return (
            f"Order({self.side.value} {self.size} @ {self.price:.2f} "
            f"{'reduce_only ' if self.reduce_only else ''}"
            f"{'post_only' if self.post_only else ''})"
        )

    @classmethod
    def from_string(cls, side: str, **kwargs):
        """Create Order with string side value"""
        return cls(side=OrderSide(side.lower()), **kwargs)

@dataclass
class PerpMarketState:
    """Enhanced market state for perpetual futures"""
    asset: str
    best_bid: float
    best_ask: float
    mark_price: float
    index_price: float
    funding_rate: float
    open_interest: float
    volume_24h: float
    position: float
    leverage: float
    account_value: float  # Added this field
    liquidation_price: Optional[float] = None
    
    @property
    def basis(self) -> float:
        """Calculate basis between mark and index price"""
        return (self.mark_price / self.index_price - 1) if self.index_price > 0 else 0
        
    @property
    def spread(self) -> float:
        """Calculate current bid-ask spread"""
        return (self.best_ask - self.best_bid) / self.best_bid if self.best_bid > 0 else 0
        
    def __str__(self):
        return (
            f"PerpMarketState(asset={self.asset}, "
            f"mark={self.mark_price:.2f}, "
            f"basis={self.basis:.4%}, "
            f"funding={self.funding_rate:.4%}, "
            f"pos={self.position:.3f})"
        )

@dataclass
class Order:
    """Represents a perpetual futures order"""
    size: float
    price: float
    side: OrderSide
    reduce_only: bool = False
    post_only: bool = True
    
    def __str__(self):
        return (
            f"Order({self.side.value} {self.size} @ {self.price:.2f} "
            f"{'reduce_only ' if self.reduce_only else ''}"
            f"{'post_only' if self.post_only else ''})"
        )