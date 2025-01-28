from abc import ABC, abstractmethod
from typing import List, Optional
from loguru import logger

from agent_smith.trading_types import PerpMarketState, Order
from agent_smith.config import TradingConfig

class PerpStrategy(ABC):
    """Base class for perpetual futures trading strategies"""
    
    def __init__(self, config: TradingConfig):
        self.config = config
        self.volatility_window = 100  # Number of samples for volatility calc
        self.price_history: List[float] = []
        
    @abstractmethod
    def should_trade(self, state: PerpMarketState) -> bool:
        """Determine if we should trade based on market conditions"""
        pass
    
    @abstractmethod
    def calculate_orders(self, state: PerpMarketState) -> List[Order]:
        """Calculate orders based on strategy logic"""
        pass
        
    def calculate_volatility(self, prices: List[float]) -> float:
        """Calculate price volatility"""
        if len(prices) < 2:
            return 0.0
            
        returns = [
            (prices[i] - prices[i-1]) / prices[i-1] 
            for i in range(1, len(prices))
        ]
        return (sum(r*r for r in returns) / len(returns)) ** 0.5

    def check_liquidation_risk(
        self,
        state: PerpMarketState,
        entry_price: float,
        size: float
    ) -> bool:
        """Check if order would create liquidation risk"""
        # Calculate new position
        new_position = state.position + size
        
        # Skip if no position
        if new_position == 0:
            return True
            
        # Calculate estimated liquidation price
        margin_requirement = 0.05  # 5% maintenance margin
        buffer = 0.02  # 2% safety buffer
        
        if new_position > 0:  # Long position
            liq_price = entry_price * (1 - (margin_requirement + buffer) * state.leverage)
            return state.index_price > liq_price
        else:  # Short position
            liq_price = entry_price * (1 + (margin_requirement + buffer) * state.leverage)
            return state.index_price < liq_price
            
    def update_price_history(self, price: float) -> None:
        """Update price history for volatility calculation"""
        self.price_history.append(price)
        if len(self.price_history) > self.volatility_window:
            self.price_history.pop(0)