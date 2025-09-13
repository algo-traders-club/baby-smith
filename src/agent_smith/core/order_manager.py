"""
Order management module.
"""

import time
from typing import List, Optional, Tuple, Dict, Any
from loguru import logger
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from agent_smith.trading_types import Order, OrderSide, PerpMarketState
from agent_smith.config import TradingConfig
from agent_smith.rate_limit import RateLimitHandler
from agent_smith.exceptions import OrderExecutionException, RateLimitException


class OrderManager:
    """Manages order execution and verification."""
    
    def __init__(self, exchange: Exchange, info: Info, config: TradingConfig, rate_limit_handler: RateLimitHandler):
        self.exchange = exchange
        self.info = info
        self.config = config
        self.rate_limit_handler = rate_limit_handler
        
    def execute_and_verify_order(self, order: Order, market_state: PerpMarketState) -> Tuple[bool, str]:
        """Execute an order and verify its fill status."""
        try:
            # Pre-execution validation
            if not self.validate_order(order, market_state.mark_price):
                return False, "Order validation failed"

            # Check rate limits
            if not self._check_rate_limits():
                raise RateLimitException("Rate limit exceeded")

            # Get starting fills for comparison
            initial_fills = self.info.user_fills(self.config.account_address)
            initial_fill_count = len(initial_fills) if initial_fills else 0

            # Execute the order
            success, message = self._execute_order(order, market_state)
            
            if not success:
                return False, message

            # Verify fill by checking new fills
            time.sleep(1)  # Brief delay to allow fill processing
            return self._verify_order_fill(initial_fill_count)

        except Exception as e:
            logger.error(f"Error executing order: {e}")
            raise OrderExecutionException(f"Order execution failed: {e}")

    def execute_perp_orders(self, orders: List[Order]) -> None:
        """Execute multiple perpetual orders with proper error handling."""
        try:
            if not orders:
                logger.info("No orders to execute")
                return

            logger.info(f"Executing {len(orders)} orders")
            
            for i, order in enumerate(orders):
                try:
                    # Get fresh market state for each order
                    market_state = self._get_current_market_state()
                    if not market_state:
                        logger.error(f"Failed to get market state for order {i+1}")
                        continue

                    success, message = self.execute_single_order(order, market_state)
                    
                    if success:
                        logger.success(f"Order {i+1}/{len(orders)} executed: {message}")
                    else:
                        logger.warning(f"Order {i+1}/{len(orders)} failed: {message}")
                        
                    # Rate limiting between orders
                    if i < len(orders) - 1:  # Don't sleep after the last order
                        time.sleep(0.5)
                        
                except Exception as e:
                    logger.error(f"Error executing order {i+1}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error in execute_perp_orders: {e}")
            raise OrderExecutionException(f"Batch order execution failed: {e}")

    def execute_single_order(self, order: Order, market_state: PerpMarketState) -> Tuple[bool, str]:
        """Execute a single order with comprehensive error handling."""
        try:
            # Validate order parameters
            if not self.validate_order(order, market_state.mark_price):
                return False, "Order validation failed"

            # Calculate slippage based on order type
            slippage = self._calculate_slippage(order, market_state)
            
            logger.info(
                f"Placing {order.side.value} order: {order.size} {self.config.asset} @ ~${order.price:.4f} "
                f"(Slippage: {slippage:.1%})"
            )

            # Execute market order
            result = self.exchange.market_open(
                name=self.config.asset,
                is_buy=order.side == OrderSide.BUY,
                sz=order.size,
                slippage=slippage
            )

            # Check immediate result
            if result.get("status") != "ok":
                error_msg = str(result.get("response", "Unknown error"))
                logger.warning(f"Order failed: {error_msg}")
                return False, error_msg

            logger.success("Order executed successfully")
            return True, "Order executed"

        except Exception as e:
            logger.error(f"Error executing single order: {e}")
            return False, str(e)

    def execute_market_order(
        self,
        side: OrderSide,
        size: float,
        slippage: float = 0.01,
        reduce_only: bool = False
    ) -> Tuple[bool, float]:
        """Execute a market order with specified parameters."""
        try:
            if reduce_only:
                # Use market_close for reduce-only orders
                result = self.exchange.market_close(
                    coin=self.config.asset,
                    sz=size,
                    slippage=slippage
                )
            else:
                # Use market_open for regular orders
                result = self.exchange.market_open(
                    name=self.config.asset,
                    is_buy=side == OrderSide.BUY,
                    sz=size,
                    slippage=slippage
                )

            if result.get("status") == "ok":
                # Extract fill price from response
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    fill = statuses[0]["filled"]
                    fill_price = float(fill["avgPx"])
                    logger.success(
                        f"Market order filled: {size} @ ${fill_price:.4f}"
                    )
                    return True, fill_price
                    
            return False, 0.0

        except Exception as e:
            logger.error(f"Error executing market order: {e}")
            raise OrderExecutionException(f"Market order execution failed: {e}")

    def cancel_all_orders(self) -> None:
        """Cancel all open orders."""
        try:
            result = self.exchange.cancel_all_orders(self.config.asset)
            
            if result.get("status") == "ok":
                logger.info("All orders cancelled successfully")
            else:
                logger.warning(f"Failed to cancel orders: {result}")
                
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")
            raise OrderExecutionException(f"Failed to cancel orders: {e}")

    def has_existing_orders(self, asset: str) -> bool:
        """Check if there are existing open orders for the asset."""
        try:
            open_orders = self.info.open_orders(self.config.account_address)
            
            if not open_orders:
                return False
                
            # Check for orders on this asset
            for order in open_orders:
                if order.get('coin') == asset:
                    return True
                    
            return False
            
        except Exception as e:
            logger.error(f"Error checking existing orders: {e}")
            return False

    def validate_order(self, order: Order, current_price: float) -> bool:
        """Validate order parameters before execution."""
        try:
            # Basic parameter validation
            if order.size <= 0:
                logger.warning(f"Invalid order size: {order.size}")
                return False
                
            if order.price <= 0:
                logger.warning(f"Invalid order price: {order.price}")
                return False
                
            # Check minimum notional value
            notional = order.size * order.price
            if notional < 12.0:
                logger.warning(f"Order notional ${notional:.2f} below minimum $12.00")
                return False
                
            # Check price deviation from current price
            price_deviation = abs(order.price - current_price) / current_price
            if price_deviation > 0.1:  # 10% deviation
                logger.warning(f"Order price deviates {price_deviation:.1%} from current price")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error validating order: {e}")
            return False

    def validate_and_format_order(self, order: Order, market_state: PerpMarketState) -> Tuple[bool, Optional[Order]]:
        """Validate and format order for execution."""
        try:
            # Validate basic parameters
            if not self.validate_order(order, market_state.mark_price):
                return False, None
                
            # Round size to proper decimals
            size_decimals = self._get_size_decimals(self.config.asset)
            formatted_size = round(order.size, size_decimals)
            
            # Ensure minimum size
            if formatted_size < 0.001:
                logger.warning(f"Size too small after formatting: {formatted_size}")
                return False, None
                
            # Create formatted order
            formatted_order = Order(
                size=formatted_size,
                price=order.price,
                side=order.side,
                reduce_only=order.reduce_only,
                post_only=order.post_only
            )
            
            return True, formatted_order
            
        except Exception as e:
            logger.error(f"Error formatting order: {e}")
            return False, None

    def _execute_order(self, order: Order, market_state: PerpMarketState) -> Tuple[bool, str]:
        """Internal method to execute an order."""
        try:
            slippage = self._calculate_slippage(order, market_state)
            
            if order.reduce_only:
                result = self.exchange.market_close(
                    coin=self.config.asset,
                    sz=order.size,
                    slippage=slippage
                )
            else:
                result = self.exchange.market_open(
                    name=self.config.asset,
                    is_buy=order.side == OrderSide.BUY,
                    sz=order.size,
                    slippage=slippage
                )
            
            if result.get("status") == "ok":
                return True, "Order executed"
            else:
                error_msg = str(result.get("response", "Unknown error"))
                return False, error_msg
                
        except Exception as e:
            logger.error(f"Error in _execute_order: {e}")
            return False, str(e)

    def _verify_order_fill(self, initial_fill_count: int) -> Tuple[bool, str]:
        """Verify that an order was filled by checking new fills."""
        try:
            new_fills = self.info.user_fills(self.config.account_address)
            new_fill_count = len(new_fills) if new_fills else 0

            if new_fill_count > initial_fill_count:
                # Extract fill details
                latest_fill = new_fills[0]  # Most recent fill
                filled_size = float(latest_fill["sz"])
                filled_price = float(latest_fill["px"])
                fill_value = filled_size * filled_price

                logger.success(
                    f"Order filled: {filled_size} @ ${filled_price:.4f} "
                    f"(Value: ${fill_value:.2f})"
                )
                return True, f"Fill confirmed - ${fill_value:.2f}"
            else:
                logger.warning("No fill detected after order placement")
                return False, "No fill detected"
                
        except Exception as e:
            logger.error(f"Error verifying fill: {e}")
            return False, str(e)

    def _calculate_slippage(self, order: Order, market_state: PerpMarketState) -> float:
        """Calculate appropriate slippage for the order."""
        base_slippage = 0.01  # 1% base slippage
        
        if order.reduce_only:
            return 0.02  # Higher slippage (2%) for reduce-only orders
            
        # Adjust slippage based on spread
        spread = market_state.best_ask - market_state.best_bid
        spread_pct = spread / market_state.mark_price if market_state.mark_price > 0 else 0
        
        if spread_pct > 0.005:  # Wide spread (>0.5%)
            return min(base_slippage * 2, 0.05)  # Max 5% slippage
            
        return base_slippage

    def _check_rate_limits(self) -> bool:
        """Check if we can place an order without hitting rate limits."""
        try:
            return self.rate_limit_handler.can_place_order()
        except Exception as e:
            logger.error(f"Error checking rate limits: {e}")
            return False

    def _get_size_decimals(self, asset: str) -> int:
        """Get decimal places for order sizes."""
        size_decimals = {
            'BTC': 4,
            'ETH': 3,
            'SOL': 1,
            'AVAX': 1,
            'MATIC': 0,
            'DOGE': 0,
        }
        return size_decimals.get(asset.upper(), 3)

    def _get_current_market_state(self) -> Optional[PerpMarketState]:
        """Get current market state (placeholder - to be injected)."""
        # This would be injected from the main trading engine
        return None