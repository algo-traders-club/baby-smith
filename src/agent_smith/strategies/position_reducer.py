import time
from typing import Dict, Optional, Tuple
from loguru import logger
from hyperliquid.exchange import Exchange
from agent_smith.trading_types import PerpMarketState
from agent_smith.trading_types import OrderSide  # Fixed import to use our local OrderSide enum

class PositionReducer:
    def __init__(self, exchange: Exchange):
        self.exchange = exchange
        self.last_attempt_time = 0
        self.min_wait_time = 45  # 45s between attempts
        self.MIN_ORDER_VALUE = 12.0  # Minimum order value in USD
        self.MAX_RETRIES = 3  # Maximum retries per reduction attempt
        self.size_decimals_cache: Dict[str, int] = {}
        
    def get_size_decimals(self, asset: str) -> int:
        """Get size decimals for proper rounding"""
        if asset not in self.size_decimals_cache:
            meta = self.exchange.info.meta()
            if meta and "universe" in meta:
                for asset_info in meta["universe"]:
                    if asset_info["name"] == asset:
                        self.size_decimals_cache[asset] = asset_info["szDecimals"]
                        break
        return self.size_decimals_cache.get(asset, 3)  # Default to 3 if not found

    def calculate_reduction_size(
        self,
        current_position: float,
        target_position: float,
        mark_price: float,
        asset: str
    ) -> float:
        """Calculate optimal reduction size with proper rounding"""
        # Calculate raw reduction needed
        reduction_needed = abs(current_position - target_position)
        
        # Calculate minimum size based on minimum order value
        min_size = self.MIN_ORDER_VALUE / mark_price if mark_price > 0 else 0
        
        # Use the smaller of reduction needed and minimum size
        size = min(reduction_needed, max(min_size, 0.1))  # At least 0.1 units
        
        # Round to appropriate decimals for the asset
        decimals = self.get_size_decimals(asset)
        return round(size, decimals)

    def reduce_position(self, market_state: PerpMarketState) -> Tuple[bool, str]:
        """Reduce position using aggressive market orders"""
        try:
            # Calculate reduction size (10% of position)
            position_size = abs(market_state.position)
            min_order_value = 12.1  # Add buffer above $12 minimum
            
            # Calculate minimum size based on price
            min_size = min_order_value / market_state.mark_price
            
            # Calculate reduction size (10% of position or minimum size, whichever is larger)
            reduction_size = max(
                min_size,
                position_size * 0.10  # Reduce 10% at a time
            )
            
            # Round to proper decimals
            reduction_size = round(reduction_size, self.get_size_decimals(market_state.asset))
            
            logger.info(f"Attempting to reduce position by {reduction_size:.4f} via market order")

            # Use market_close for position reduction
            result = self.exchange.market_close(
                coin=market_state.asset,
                sz=reduction_size,
                slippage=0.01  # 1% slippage
            )

            if result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    fill = statuses[0]["filled"]
                    fill_size = float(fill["totalSz"])
                    fill_price = float(fill["avgPx"])
                    fill_value = fill_size * fill_price
                    
                    logger.success(
                        f"✅ Successfully reduced position by {fill_size:.4f} @ ${fill_price:.4f} "
                        f"(Value: ${fill_value:.2f})"
                    )
                    return True, f"Reduced by {fill_size:.4f}"
                elif statuses and "error" in statuses[0]:
                    logger.warning(f"Order error: {statuses[0]['error']}")
                    return False, f"Order error: {statuses[0]['error']}"
            
            return False, "Order not filled"
            
        except Exception as e:
            logger.error(f"Error reducing position: {e}")
            return False, str(e)