"""
Order utility functions for trading strategies.
"""

from typing import Tuple
from loguru import logger

from agent_smith.trading_types import PerpMarketState, Order, OrderSide
from agent_smith.config import TradingConfig
from agent_smith.exceptions import OrderExecutionException, ValidationException




def get_size_decimals(asset: str) -> int:
    """Get the number of decimal places for order sizes based on asset."""
    try:
        # Common asset configurations
        size_decimals = {
            'BTC': 4,
            'ETH': 3,
            'SOL': 1,
            'AVAX': 1,
            'MATIC': 0,
            'DOGE': 0,
        }
        
        return size_decimals.get(asset.upper(), 3)  # Default to 3 decimals
        
    except Exception as e:
        logger.error(f"Error getting size decimals for {asset}: {e}")
        return 3  # Safe default




def calculate_optimal_size(mark_price: float, min_notional: float = 12.0, size_multiplier: float = 1.2) -> float:
    """Calculate optimal order size based on minimum notional requirements."""
    try:
        if mark_price <= 0:
            raise ValidationException("Mark price must be positive")
            
        if min_notional <= 0:
            raise ValidationException("Minimum notional must be positive")
            
        # Calculate minimum size for notional requirement
        min_size = min_notional / mark_price
        
        # Add buffer to ensure we clear minimum
        optimal_size = min_size * size_multiplier
        
        return optimal_size
        
    except Exception as e:
        logger.error(f"Error calculating optimal size: {e}")
        raise OrderExecutionException(f"Failed to calculate optimal size: {e}")


def validate_order_parameters(order: Order, market_state: PerpMarketState) -> bool:
    """Validate order parameters before execution."""
    try:
        # Check size is positive
        if order.size <= 0:
            logger.warning(f"Invalid order size: {order.size}")
            return False
            
        # Check price is positive
        if order.price <= 0:
            logger.warning(f"Invalid order price: {order.price}")
            return False
            
        # Check minimum notional value
        order_value = order.size * order.price
        if order_value < 12.0:
            logger.warning(f"Order value ${order_value:.2f} below minimum $12.00")
            return False
            
        # Check price reasonableness (within 50% of mark price)
        price_deviation = abs(order.price - market_state.mark_price) / market_state.mark_price
        if price_deviation > 0.5:
            logger.warning(f"Order price deviates {price_deviation:.1%} from mark price")
            return False
            
        return True
        
    except Exception as e:
        logger.error(f"Error validating order: {e}")
        return False


def calculate_spread_metrics(market_state: PerpMarketState) -> dict:
    """Calculate spread-related metrics."""
    try:
        spread = market_state.best_ask - market_state.best_bid
        mid_price = (market_state.best_bid + market_state.best_ask) / 2
        spread_bps = (spread / mid_price) * 10000 if mid_price > 0 else 0
        
        return {
            'spread': spread,
            'mid_price': mid_price,
            'spread_bps': spread_bps,
            'spread_pct': spread / mid_price if mid_price > 0 else 0
        }
        
    except Exception as e:
        logger.error(f"Error calculating spread metrics: {e}")
        return {}




def adjust_size_for_decimals(size: float, asset: str) -> float:
    """Adjust order size to proper decimal places."""
    try:
        decimals = get_size_decimals(asset)
        return round(size, decimals)
        
    except Exception as e:
        logger.error(f"Error adjusting size decimals: {e}")
        return size


