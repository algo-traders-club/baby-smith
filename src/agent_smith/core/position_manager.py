"""
Position management module.
"""

from typing import Optional, Dict
from loguru import logger
from datetime import datetime

from agent_smith.trading_types import PerpMarketState
from agent_smith.config import TradingConfig
from agent_smith.exceptions import PositionManagementException


class PositionManager:
    """Manages position tracking and risk monitoring."""
    
    def __init__(self, config: TradingConfig):
        self.config = config
        self.position_entry_price: Optional[float] = None
        self.position_entry_time: Optional[datetime] = None
        self.last_position_size = 0.0
        
    def update_position_state(self, market_state: PerpMarketState, entry_price: Optional[float] = None) -> None:
        """Update internal position state tracking."""
        try:
            current_position = market_state.position
            
            # Detect position changes
            if abs(current_position - self.last_position_size) > 0.001:
                logger.info(f"Position changed: {self.last_position_size:.4f} -> {current_position:.4f}")
                
                # Update entry price if position increased
                if abs(current_position) > abs(self.last_position_size):
                    if entry_price:
                        self.position_entry_price = entry_price
                        self.position_entry_time = datetime.now()
                        logger.info(f"Updated entry price: ${entry_price:.4f}")
                        
                # Clear entry price if position closed
                elif current_position == 0.0:
                    self.position_entry_price = None
                    self.position_entry_time = None
                    logger.info("Position closed - cleared entry price")
                    
                self.last_position_size = current_position
                
        except Exception as e:
            logger.error(f"Error updating position state: {e}")
            raise PositionManagementException(f"Failed to update position state: {e}")
            
    def check_position_status(self, market_state: PerpMarketState) -> None:
        """Check and log position status with risk metrics."""
        try:
            position = market_state.position
            
            if position == 0:
                logger.info("Position: FLAT")
                return
                
            # Calculate position metrics
            position_size = abs(position)
            utilization = position_size / self.config.max_position
            direction = "LONG" if position > 0 else "SHORT"
            
            # Calculate unrealized PnL if we have entry price
            unrealized_pnl = None
            pnl_pct = None
            
            if self.position_entry_price:
                if position > 0:  # Long position
                    unrealized_pnl = (market_state.mark_price - self.position_entry_price) * position_size
                else:  # Short position
                    unrealized_pnl = (self.position_entry_price - market_state.mark_price) * position_size
                    
                pnl_pct = unrealized_pnl / (self.position_entry_price * position_size) if self.position_entry_price > 0 else 0
                
            # Log position status
            status_msg = (
                f"Position: {direction} {position_size:.4f} {self.config.asset} "
                f"({utilization:.1%} of max) @ ${market_state.mark_price:.4f}"
            )
            
            if unrealized_pnl is not None:
                status_msg += f" | PnL: ${unrealized_pnl:.2f} ({pnl_pct:.2%})"
                
            logger.info(status_msg)
            
        except Exception as e:
            logger.error(f"Error checking position status: {e}")
            
    def should_reduce_position(self, position_size: float) -> bool:
        """Check if position should be reduced based on size and risk."""
        try:
            # Check if position exceeds 80% of max
            utilization = abs(position_size) / self.config.max_position
            return utilization > 0.8
            
        except Exception as e:
            logger.error(f"Error checking position reduction: {e}")
            return False
            
    def validate_position_state(self, market_state: PerpMarketState) -> bool:
        """Validate position state for consistency."""
        try:
            position = market_state.position
            
            # Check position within limits
            if abs(position) > self.config.max_position:
                logger.error(f"Position {position:.4f} exceeds max {self.config.max_position}")
                return False
                
            # Check for reasonable position size
            if abs(position) > 0 and abs(position) < 0.001:
                logger.warning(f"Very small position detected: {position:.6f}")
                
            return True
            
        except Exception as e:
            logger.error(f"Error validating position state: {e}")
            return False
            
    def check_position_limits(self, market_state: PerpMarketState, size: float, is_buy: bool) -> bool:
        """Check if a trade would exceed position limits."""
        try:
            current_position = market_state.position
            
            # Calculate new position after trade
            new_position = current_position + (size if is_buy else -size)
            
            # Check against maximum position
            if abs(new_position) > self.config.max_position:
                logger.warning(
                    f"Trade would exceed position limit: "
                    f"Current={current_position:.4f}, New={new_position:.4f}, Max={self.config.max_position}"
                )
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error checking position limits: {e}")
            raise PositionManagementException(f"Position limit check failed: {e}")
            
    def get_position_metrics(self, market_state: PerpMarketState) -> Dict[str, float]:
        """Get comprehensive position metrics."""
        try:
            position = market_state.position
            position_size = abs(position)
            
            metrics = {
                'position_size': position_size,
                'position_direction': 1.0 if position > 0 else (-1.0 if position < 0 else 0.0),
                'utilization': position_size / self.config.max_position,
                'remaining_capacity': self.config.max_position - position_size,
                'mark_price': market_state.mark_price
            }
            
            # Add PnL metrics if we have entry price
            if self.position_entry_price and position != 0:
                if position > 0:  # Long
                    unrealized_pnl = (market_state.mark_price - self.position_entry_price) * position_size
                else:  # Short
                    unrealized_pnl = (self.position_entry_price - market_state.mark_price) * position_size
                    
                pnl_pct = unrealized_pnl / (self.position_entry_price * position_size) if self.position_entry_price > 0 else 0
                
                metrics.update({
                    'entry_price': self.position_entry_price,
                    'unrealized_pnl': unrealized_pnl,
                    'pnl_percentage': pnl_pct
                })
                
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating position metrics: {e}")
            return {}
            
    def log_position_state(self, market_state: PerpMarketState) -> None:
        """Log detailed position state information."""
        try:
            metrics = self.get_position_metrics(market_state)
            
            if metrics.get('position_size', 0) == 0:
                logger.info("Position: FLAT")
                return
                
            direction = "LONG" if metrics.get('position_direction', 0) > 0 else "SHORT"
            size = metrics.get('position_size', 0)
            utilization = metrics.get('utilization', 0)
            mark_price = metrics.get('mark_price', 0)
            
            log_msg = f"Position: {direction} {size:.4f} ({utilization:.1%}) @ ${mark_price:.4f}"
            
            if 'unrealized_pnl' in metrics:
                pnl = metrics['unrealized_pnl']
                pnl_pct = metrics.get('pnl_percentage', 0)
                log_msg += f" | PnL: ${pnl:.2f} ({pnl_pct:.2%})"
                
            logger.info(log_msg)
            
        except Exception as e:
            logger.error(f"Error logging position state: {e}")
            
    def get_entry_price(self) -> Optional[float]:
        """Get current position entry price."""
        return self.position_entry_price
        
    def clear_position_tracking(self) -> None:
        """Clear position tracking data (for testing/reset)."""
        self.position_entry_price = None
        self.position_entry_time = None
        self.last_position_size = 0.0