"""
Risk management module for trading strategies.
"""

from typing import Dict, List, Optional
from datetime import datetime
from loguru import logger
import numpy as np

from agent_smith.trading_types import PerpMarketState, Order, OrderSide
from agent_smith.config import TradingConfig
from agent_smith.exceptions import RiskManagementException


class DynamicRiskManager:
    """Handles risk management for trading strategies."""
    
    def __init__(
        self,
        config: TradingConfig,
        max_position: float = 5.0,
        profit_take_threshold: float = 0.012,
        stop_loss_threshold: float = 0.015,
        max_losing_trades: int = 3
    ):
        self.config = config
        self.max_position = max_position
        self.profit_take_threshold = profit_take_threshold
        self.stop_loss_threshold = stop_loss_threshold
        self.max_losing_trades = max_losing_trades
        self.trade_history: List[Dict] = []
        
    def validate_trade(self, order: Order, market_state: PerpMarketState) -> bool:
        """Enhanced trade validation with risk checks."""
        try:
            # Check minimum order value 
            order_value = order.size * market_state.mark_price
            if order_value < 12.0:
                logger.warning(f"Order value ${order_value:.2f} below minimum $12.00")
                return False
                
            # Check maximum position size
            new_position = self._calculate_new_position(order, market_state)
            if abs(new_position) > self.max_position:
                logger.warning(f"New position {new_position:.4f} would exceed max {self.max_position}")
                return False
                
            # Check recent performance
            if not self._check_recent_performance():
                return False
                    
            return True
            
        except Exception as e:
            logger.error(f"Error validating trade: {e}")
            raise RiskManagementException(f"Trade validation failed: {e}")
            
    def check_position_limits(self, market_state: PerpMarketState, size: float, is_buy: bool) -> bool:
        """Check position limits with reduce-only handling."""
        try:
            current_position = market_state.position
            
            # Always allow reduce-only orders
            if self._is_reducing_position(current_position, size, is_buy):
                return True
                
            # Calculate new position
            new_position = current_position + (size if is_buy else -size)
            
            # Check max position limit
            if abs(new_position) > self.config.max_position:
                logger.warning(
                    f"Position limit check failed: Current={current_position:.4f}, "
                    f"New would be={new_position:.4f}, Max={self.config.max_position}"
                )
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error checking position limits: {e}")
            raise RiskManagementException(f"Position limit check failed: {e}")
            
    def should_take_profit(self, market_state: PerpMarketState, entry_price: Optional[float]) -> bool:
        """Check if profit taking conditions are met."""
        if not entry_price or market_state.position == 0:
            return False
            
        try:
            current_price = market_state.mark_price
            profit_pct = abs(current_price - entry_price) / entry_price
            
            return profit_pct >= self.profit_take_threshold
            
        except Exception as e:
            logger.error(f"Error checking profit taking: {e}")
            return False
            
    def should_stop_loss(self, market_state: PerpMarketState, entry_price: Optional[float]) -> bool:
        """Check if stop loss conditions are met."""
        if not entry_price or market_state.position == 0:
            return False
            
        try:
            current_price = market_state.mark_price
            is_long = market_state.position > 0
            
            if is_long:
                loss_pct = (entry_price - current_price) / entry_price
            else:
                loss_pct = (current_price - entry_price) / entry_price
                
            return loss_pct >= self.stop_loss_threshold
            
        except Exception as e:
            logger.error(f"Error checking stop loss: {e}")
            return False
            
    def update_trade_history(self, fill_price: float, fill_size: float, pnl: float) -> None:
        """Update trade history for risk tracking."""
        try:
            self.trade_history.append({
                'timestamp': datetime.now(),
                'price': fill_price,
                'size': fill_size,
                'pnl': pnl
            })
            
            # Keep only last 100 trades
            if len(self.trade_history) > 100:
                self.trade_history = self.trade_history[-100:]
                
        except Exception as e:
            logger.error(f"Error updating trade history: {e}")
            
    def get_risk_metrics(self) -> Dict[str, float]:
        """Calculate current risk metrics."""
        if not self.trade_history:
            return {}
            
        try:
            recent_trades = [t for t in self.trade_history 
                           if (datetime.now() - t['timestamp']).total_seconds() < 86400]
            
            if not recent_trades:
                return {}
                
            pnls = [t['pnl'] for t in recent_trades]
            winning_trades = [pnl for pnl in pnls if pnl > 0]
            
            return {
                'total_trades': len(recent_trades),
                'winning_trades': len(winning_trades),
                'win_rate': len(winning_trades) / len(recent_trades) if recent_trades else 0,
                'total_pnl': sum(pnls),
                'avg_pnl': np.mean(pnls),
                'max_drawdown': min(pnls) if pnls else 0
            }
            
        except Exception as e:
            logger.error(f"Error calculating risk metrics: {e}")
            return {}
            
    def _calculate_new_position(self, order: Order, market_state: PerpMarketState) -> float:
        """Calculate new position after order execution."""
        current_position = market_state.position
        
        if order.side == OrderSide.BUY:
            return current_position + order.size
        else:
            return current_position - order.size
            
    def _is_reducing_position(self, current_position: float, size: float, is_buy: bool) -> bool:
        """Check if order reduces the current position."""
        if current_position > 0 and not is_buy:
            return True  # Sell to reduce long
        if current_position < 0 and is_buy:
            return True  # Buy to reduce short
        return False
        
    def _check_recent_performance(self) -> bool:
        """Check if recent performance allows for new trades."""
        if len(self.trade_history) >= 3:
            recent_trades = self.trade_history[-3:]
            losing_trades = sum(1 for t in recent_trades if t['pnl'] < 0)
            if losing_trades >= 2:
                logger.warning("Too many recent losses - skipping trade")
                return False
                
        return True