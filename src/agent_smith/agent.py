import json
import time
from typing import Dict, Optional, List, Tuple 
import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from loguru import logger
from datetime import datetime, timedelta

from agent_smith.config import TradingConfig
from agent_smith.metrics import MetricsTracker
from agent_smith.trading_types import PerpMarketState, Order, OrderSide
from agent_smith.strategies.market_maker import AggressiveMarketMaker
from agent_smith.rate_limit import RateLimitHandler
from agent_smith.strategies.position_reducer import PositionReducer

from agent_smith.logging_utils import (
    logger,
    print_status_update,
    console
)

class AgentSmith:
    """Trading agent for perpetual futures on Hyperliquid"""
    def __init__(self, config: TradingConfig):
        """Initialize the trading agent"""
        try:
            # Initialize clients first
            self.info = Info(base_url=config.exchange_url)
            logger.info("Info client initialized")
            
            # Initialize exchange client
            wallet = eth_account.Account.from_key(config.secret_key)
            self.exchange = Exchange(
                wallet=wallet,
                base_url=config.exchange_url,
                account_address=config.account_address
            )
            logger.info("Exchange client initialized")
            
            # Initialize components
            self.config = config
            self.rate_limit_handler = RateLimitHandler()
            self.position_reducer = PositionReducer(exchange=self.exchange)
            logger.info("Position reducer initialized")
            
            # Get accurate initial state with entry price
            initial_state = self.get_accurate_position_state(self.info, config.account_address)
            self.position = initial_state['position']
            self.entry_price = initial_state['entry_price']  # Add this
            self.account_value = initial_state['account_value']
            self.current_price = initial_state['current_price']
            
            # Calculate initial PnL
            if self.position != 0 and self.entry_price != 0:
                pnl = (self.current_price - self.entry_price) * self.position
                initial_state['pnl'] = pnl
            
            # Single status update
            print_status_update(initial_state)
            
            # Initialize strategy
            self.strategy = AggressiveMarketMaker(
                config=config,
                base_position=0.25,
                max_position=config.max_position,
                min_order_interval=60,
                profit_take_threshold=0.012,
                stop_loss_threshold=0.015,
                momentum_window=20,
                momentum_threshold=0.003,
                min_notional=12.0
            )
            
            logger.success("Agent initialization complete with conservative strategy")
            
        except Exception as e:
            logger.error(f"Failed to initialize agent: {str(e)}")
            raise

    def get_size_decimals(self, asset: str) -> int:
        """Get size decimals for asset from exchange metadata"""
        try:
            # Check cache first
            if not hasattr(self, '_size_decimals_cache'):
                self._size_decimals_cache = {}
                
            if asset not in self._size_decimals_cache:
                meta = self.info.meta()
                if meta and "universe" in meta:
                    for asset_info in meta["universe"]:
                        if asset_info["name"] == asset:
                            self._size_decimals_cache[asset] = asset_info["szDecimals"]
                            break
                            
            return self._size_decimals_cache.get(asset, 3)  # Default to 3 decimals
            
        except Exception as e:
            logger.error(f"Error getting size decimals: {e}")
            return 3  # Safe default

    def calculate_market_price(self, base_price: float, is_buy: bool, slippage: float = 0.02) -> float:
        """Calculate market order price with slippage"""
        # Add slippage in correct direction
        adjustment = 1 + slippage if is_buy else 1 - slippage
        # Round to 4 decimal places
        return round(base_price * adjustment, 4)

    def can_place_order(self) -> bool:
        """Check if enough time has passed since last order"""
        current_time = time.time()
        time_since_last = current_time - self.last_order_time
        
        if time_since_last < self.order_cooldown:
            logger.info(f"Order cooldown: {int(self.order_cooldown - time_since_last)}s remaining")
            return False
        return True

    def round_price(self, price: float) -> float:
        """Round price to valid tick size"""
        try:
            # First round to 5 significant figures
            str_price = f"{price:.5g}"
            # Then ensure max 4 decimal places
            rounded = round(float(str_price), 4)
            # Ensure divisible by tick size
            tick_size = 0.0001
            return round(rounded / tick_size) * tick_size
        except Exception as e:
            logger.error(f"Error rounding price: {e}")
            return price  # Return original on error

    def rate_limit_handler(self):
        """Check and update rate limit state"""
        current_time = time.time()
        
        # Always wait minimum time between orders
        if hasattr(self, 'last_order_time'):
            time_since_last = current_time - self.last_order_time
            min_wait = 10  # 10 second minimum between orders
            if time_since_last < min_wait:
                return False, f"Minimum wait not met ({min_wait - time_since_last:.1f}s remaining)"
        
        # Check if we're in cooldown
        if hasattr(self, 'rate_limit_cooldown') and current_time < self.rate_limit_cooldown:
            remaining = self.rate_limit_cooldown - current_time
            return False, f"Rate limit cooldown ({remaining:.1f}s remaining)"
            
        return True, "OK"

    def on_rate_limit(self):
        """Handle rate limit error"""
        # Exponential backoff
        if not hasattr(self, 'rate_limit_count'):
            self.rate_limit_count = 0
        
        self.rate_limit_count += 1
        cooldown = min(30 * (2 ** (self.rate_limit_count - 1)), 300)  # Max 5 minute cooldown
        
        self.rate_limit_cooldown = time.time() + cooldown
        logger.warning(f"Rate limited - cooling down for {cooldown}s")

    def execute_volume_building_order(self, market_state: PerpMarketState) -> Tuple[bool, float]:
        """Execute a market order for volume building"""
        try:
            # Calculate size based on $12 minimum order value
            min_order_value = 12.0
            size = max(min_order_value / market_state.mark_price, 0.1)  # At least 0.1 units
            size = round(size * 1.2, 3)  # Add 20% buffer and round to 3 decimals
            
            # Alternate between buy and sell
            timestamp = int(time.time())
            is_buy = (timestamp % 2) == 0  # Buy on even seconds, sell on odd
            
            logger.info(f"Placing market {is_buy and 'buy' or 'sell'} order: {size:.3f} @ market")
            
            # Place market order with 2% slippage
            result = self.exchange.market_open(
                name=self.config.asset,
                is_buy=is_buy,
                sz=size,
                slippage=0.02
            )
            
            if result.get("status") == "ok":
                # Extract fill information
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    fill = statuses[0]["filled"]
                    fill_size = float(fill["totalSz"])
                    fill_price = float(fill["avgPx"])
                    fill_value = fill_size * fill_price
                    
                    logger.success(
                        f"✅ Fill success: {fill_size:.4f} {self.config.asset} @ "
                        f"${fill_price:.4f} (Value: ${fill_value:.2f})"
                    )
                    
                    self.rate_limit_handler.on_success(fill_value)
                    return True, fill_value
                    
                elif statuses and "error" in statuses[0]:
                    logger.warning(f"Order error: {statuses[0]['error']}")
                    return False, 0.0
                    
            elif "Too many cumulative requests" in str(result):
                self.rate_limit_handler.on_rate_limit_error()
                return False, 0.0
                
            return False, 0.0
            
        except Exception as e:
            logger.error(f"Error executing order: {str(e)}")
            return False, 0.0

    def setup_builder_fee(self) -> bool:
        """Setup and approve builder fee"""
        try:
            logger.info("Setting up builder fee approval...")
            
            # Approve builder fee (0.1%)
            result = self.exchange.approve_builder_fee(
                builder="0x8c967E73E7B15087c42A10D344cFf4c96D877f1D",
                max_fee_rate="0.1%"
            )
            
            if result.get("status") == "ok":
                logger.success("Builder fee approved successfully")
                return True
            else:
                logger.error(f"Failed to approve builder fee: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error setting up builder fee: {str(e)}")
            return False

    def _set_initial_leverage(self) -> None:
        """Set the initial leverage for trading with timeout"""
        try:
            # Get current leverage
            user_state = self.info.user_state(self.config.account_address)
            if not user_state:
                raise Exception("Could not get user state")
                
            current_leverage = None
            if 'assetPositions' in user_state:
                for position in user_state['assetPositions']:
                    if position['position']['coin'] == self.config.asset:
                        leverage_data = position['position'].get('leverage', {'value': '1'})
                        current_leverage = int(leverage_data.get('value', 1))
                        break
            
            # Set leverage if different from config
            if current_leverage != self.config.leverage:
                logger.info(f"Setting leverage to {self.config.leverage}x for {self.config.asset}")
                result = self.exchange.update_leverage(
                    self.config.leverage,
                    self.config.asset,
                    is_cross=True
                )
                if result.get('status') != 'ok':
                    raise Exception(f"Failed to set leverage: {result}")
                logger.success(f"Leverage set successfully to {self.config.leverage}x")
            else:
                logger.info(f"Leverage already set to {self.config.leverage}x")
                
        except Exception as e:
            logger.error(f"Failed to set leverage: {str(e)}")

    def check_position_status(self, market_state: PerpMarketState) -> None:
        """More aggressive position monitoring"""
        try:
            position_size = abs(market_state.position)
            max_allowed = self.config.max_position

            # Calculate position usage
            position_usage = position_size / max_allowed if max_allowed > 0 else 0
            
            logger.info(f"Position usage {position_usage:.1%} ({position_size:.4f}/{max_allowed:.1f})")
            
            # Take action at 85% usage instead of 90%
            if position_usage >= 0.85:  # Lowered threshold
                logger.warning(f"Position usage {position_usage:.1%} above target")
                
                # Check for existing orders
                open_orders = self.info.open_orders(self.config.account_address)
                has_orders = any(
                    order['coin'] == market_state.asset 
                    for order in open_orders
                )
                
                if not has_orders:
                    logger.info("No existing orders, attempting position reduction")
                    self.handle_max_position(market_state)
                else:
                    # Cancel existing orders if they're older than 60 seconds
                    for order in open_orders:
                        if order['coin'] == market_state.asset:
                            order_age = time.time() - (order['timestamp'] / 1000)
                            if order_age > 60:
                                logger.info(f"Cancelling old order {order['oid']}")
                                self.exchange.cancel(market_state.asset, order['oid'])

        except Exception as e:
            logger.error(f"Error checking position status: {e}")
    
    def check_rate_limits(self) -> bool:
        current_time = time.time()
        
        # Reset counters every hour
        if current_time - self.last_reset_time > 3600:
            self.request_count = 0
            self.volume_traded = 0
            self.last_reset_time = current_time
            
        # Allow 1 request per 1 USDC traded
        max_requests = int(self.volume_traded) + 10000  # Base allowance of 10k requests
        return self.request_count < max_requests

    def validate_order(self, order: Order, current_price: float) -> bool:
        """Validate order parameters before submission"""
        try:
            # Check minimum order value ($12 minimum)
            order_value = order.size * current_price
            if order_value < 12.0:
                logger.warning(f"Order value ${order_value:.2f} below minimum $12.00")
                return False

            # Check price deviation (max 5% from current price)
            price_diff = abs(order.price - current_price) / current_price
            if price_diff > 0.05:
                logger.warning(f"Price deviation {price_diff:.1%} exceeds 5% maximum")
                return False

            # Verify size is properly rounded
            rounded_size = round(order.size, 3)  # Round to 3 decimal places
            if rounded_size != order.size:
                logger.warning(f"Order size {order.size} not properly rounded")
                return False

            # All validations passed
            return True

        except Exception as e:
            logger.error(f"Error validating order: {e}")
            return False

    def verify_order_fill(
        self,
        initial_fills: List[Dict],
        result: Dict,
        expected_size: float
    ) -> Tuple[bool, float]:
        """Verify order was filled properly"""
        try:
            if result.get("status") != "ok":
                return False, 0.0
                
            # Get new fills
            time.sleep(1)  # Wait for fill
            new_fills = self.info.user_fills(self.config.account_address)
            
            # Check for new fill
            if len(new_fills) <= len(initial_fills):
                return False, 0.0
                
            # Get latest fill
            latest_fill = new_fills[0]
            filled_size = float(latest_fill["sz"])
            filled_price = float(latest_fill["px"])
            
            # Calculate fill value
            fill_value = filled_size * filled_price
            
            return True, fill_value
            
        except Exception as e:
            logger.error(f"Error verifying fill: {e}")
            return False, 0.0

    def execute_and_verify_order(self, order: Order, market_state: PerpMarketState) -> Tuple[bool, str]:
        """Execute an order and verify its fill status"""
        try:
            # Pre-execution validation
            if not self.validate_order(order, market_state.mark_price):
                return False, "Order validation failed"

            # Get starting user state for comparison
            initial_fills = self.info.user_fills(self.config.account_address)
            initial_fill_count = len(initial_fills) if initial_fills else 0

            # Place the order
            params = self.rate_limit_handler.get_order_params()
            price_adjust = 0.0005  # 0.05% price adjustment

            # Calculate final price
            adjusted_price = order.price * (
                1 + price_adjust if order.side == OrderSide.BUY else 1 - price_adjust
            )

            logger.info(
                f"Placing taker {order.side.value} order: {order.size} {self.config.asset} "
                f"@ ${adjusted_price:.4f}"
            )

            # Execute the order
            result = self.exchange.order(
                name=self.config.asset,
                is_buy=order.side == OrderSide.BUY,
                sz=order.size,
                limit_px=adjusted_price,
                order_type={"limit": {"tif": "Ioc"}},  # Use IOC for guaranteed fill or cancel
                reduce_only=order.reduce_only,
                builder={  # Always use builder for better fills
                    "b": "0x8c967E73E7B15087c42A10D344cFf4c96D877f1D",
                    "f": 1
                }
            )

            # Check immediate result
            if result.get("status") != "ok":
                error_msg = str(result.get("response", "Unknown error"))
                logger.warning(f"Order not filled: {error_msg}")
                return False, error_msg

            # Verify fill by checking new fills
            time.sleep(1)  # Brief delay to allow fill processing
            new_fills = self.info.user_fills(self.config.account_address)
            new_fill_count = len(new_fills) if new_fills else 0

            if new_fill_count > initial_fill_count:
                # Extract fill details
                latest_fill = new_fills[0]  # Most recent fill
                filled_size = float(latest_fill["sz"])
                filled_price = float(latest_fill["px"])
                fill_value = filled_size * filled_price

                # Update volume tracking
                self.rate_limit_handler.on_fill_success(fill_value)

                logger.success(
                    f"Order verified - Filled {filled_size} @ ${filled_price:.4f} "
                    f"(Value: ${fill_value:.2f})"
                )
                return True, f"Fill confirmed - ${fill_value:.2f}"
            else:
                logger.warning("No fill detected after order placement")
                return False, "No fill detected"

        except Exception as e:
            logger.error(f"Error executing order: {str(e)}")
            return False, str(e)


    def execute_perp_orders(self, orders: List[Order]) -> None:
        """Execute perpetual futures orders with enhanced error handling"""
        if not orders:
            return

        try:
            # Check rate limits before processing orders
            can_trade, message = self.rate_limit_handler.can_trade()
            if not can_trade:
                logger.warning(f"Rate limit check failed: {message}")
                return

            market_state = self.get_perp_market_state()
            if not market_state:
                logger.warning("Could not get market state")
                return
                    
            for order in orders:
                try:
                    # Get appropriate slippage based on market conditions
                    slippage = self.rate_limit_handler.get_slippage()
                    
                    # Validate and adjust order
                    is_valid, adjusted_order = self.validate_and_adjust_order(
                        order=order,
                        market_state=market_state
                    )
                        
                    if not is_valid:
                        logger.warning("Order validation failed, skipping")
                        continue
                        
                    logger.info(
                        f"Placing market {adjusted_order.side.value} order: "
                        f"{adjusted_order.size} {self.config.asset} @ ~${market_state.mark_price:.4f} "
                        f"(Slippage: {slippage:.1%})"
                    )
                        
                    # Place market order
                    result = self.exchange.market_open(
                        name=self.config.asset,
                        is_buy=adjusted_order.side == OrderSide.BUY,
                        sz=adjusted_order.size,
                        slippage=slippage
                    )
                        
                    # Process the result
                    if result.get("status") == "ok":
                        statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                        if statuses and "filled" in statuses[0]:
                            fill = statuses[0]["filled"]
                            fill_size = float(fill["totalSz"])
                            fill_price = float(fill["avgPx"])
                            fill_value = fill_size * fill_price
                                
                            logger.success(
                                f"✅ Order filled: {fill_size} @ ${fill_price:.4f} "
                                f"(Value: ${fill_value:.2f})"
                            )
                            self.rate_limit_handler.on_success(fill_value)
                                
                        elif statuses and "error" in statuses[0]:
                            error_msg = statuses[0]["error"]
                            if "MinTradeNtl" in error_msg:
                                logger.warning(f"Order below minimum value: {error_msg}")
                            else:
                                logger.error(f"Order error: {error_msg}")
                                    
                    elif "Too many cumulative requests" in str(result):
                        logger.warning("Rate limited, increasing backoff")
                        self.rate_limit_handler.on_rate_limit_error()
                        break  # Stop processing more orders
                            
                    else:
                        logger.error(f"Unknown order error: {result}")
                        
                except Exception as e:
                    logger.error(f"Error placing individual order: {str(e)}")
                    continue

                # Brief pause between orders
                time.sleep(1)

        except Exception as e:
            logger.error(f"Error in execute_perp_orders: {str(e)}")

    def calculate_mid_price(best_bid: float, best_ask: float) -> float:
        """Calculate properly formatted mid price"""
        mid = (best_bid + best_ask) / 2
        return format_price(mid)
            
    def calculate_optimal_size(self, mark_price: float) -> float:
        """Calculate optimal order size to maximize volume while managing risk"""
        # Minimum value is $12
        min_size = 12.0 / mark_price if mark_price > 0 else 0
        
        # Scale size up as volume increases
        volume_multiplier = min(2.0, 1 + (self.rate_limit_handler.volume_traded / 1000))
        
        # Calculate size with volume scaling
        size = min_size * volume_multiplier
        
        # Round to 3 decimal places
        return round(size, 3)

    def calculate_spread_adjustment(self, volume_traded: float) -> float:
        base_spread = 0.002  # 0.2% base spread
        
        # Tighten spread based on volume
        if volume_traded > 100:
            spread_reduction = min(0.0015, (volume_traded / 1000) * 0.002)
            return max(0.0005, base_spread - spread_reduction)
        
        return base_spread
    
    def execute_market_order(
        self, 
        market_state: PerpMarketState,
        size: float
    ) -> Tuple[bool, float]:
        try:
            # Add safety buffer to minimum size
            min_value = 12.1  # Add buffer above $12 minimum
            min_size = min_value / market_state.mark_price
            size = max(size, min_size)
            
            # Round to proper decimals
            size = round(size, self.get_size_decimals(market_state.asset))
            
            # Use IOC order with builder fee for reliable execution
            result = self.exchange.order(
                name=market_state.asset,
                is_buy=market_state.position < 0,  # Buy to reduce short, sell to reduce long
                sz=size,
                limit_px=market_state.mark_price * (1.005 if market_state.position < 0 else 0.995),
                order_type={"limit": {"tif": "Ioc"}},
                reduce_only=True,
                builder={
                    "b": "0x8c967E73E7B15087c42A10D344cFf4c96D877f1D",
                    "f": 1
                }
            )

            if result.get("status") == "ok":
                fill = result["response"]["data"]["statuses"][0].get("filled")
                if fill:
                    return True, float(fill["avgPx"]) * float(fill["totalSz"])
            
            return False, 0.0

        except Exception as e:
            logger.error(f"Error executing market order: {e}")
            return False, 0.0


    def get_trade_side(self, last_trade_was_buy: bool, market_state: PerpMarketState) -> bool:
        """Determine optimal trade side based on market conditions"""
        # Base case: alternate sides
        is_buy = not last_trade_was_buy
        
        # Check if large imbalance exists
        bid_size = market_state.best_bid_size
        ask_size = market_state.best_ask_size
        
        if bid_size > ask_size * 1.5:
            # Strong buying pressure - join the buyers
            is_buy = True
        elif ask_size > bid_size * 1.5:
            # Strong selling pressure - join the sellers
            is_buy = False
            
        return is_buy

    def cancel_all_orders(self) -> None:
        """Cancel all open orders"""
        try:
            open_orders = self.info.open_orders(self.config.account_address)
            cancelled = 0
            
            for order in open_orders:
                if order["coin"] == self.config.asset:
                    result = self.exchange.cancel(self.config.asset, order["oid"])
                    if result["status"] == "ok":
                        cancelled += 1
                        if order["oid"] in self.current_orders:
                            del self.current_orders[order["oid"]]
                            
            if cancelled > 0:
                logger.info(f"Cancelled {cancelled} open orders")
                
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")

    def calculate_valid_size(
        self,
        price: float,
        min_value: float = 12.0,
        size_decimals: Optional[int] = None
    ) -> float:
        """Calculate valid order size for given price"""
        if size_decimals is None:
            size_decimals = self.get_size_decimals(self.config.asset)
            
        # Calculate minimum size based on minimum value
        min_size = min_value / price if price > 0 else 0
        
        # Round to appropriate decimals
        size = round(min_size * 1.05, size_decimals)  # Add 5% buffer
        
        # Ensure minimum size
        size = max(size, 0.001)  # 0.001 minimum for most assets
        
        return size

    def get_size_decimals(self, asset: str) -> int:
        """Get size decimals for proper rounding"""
        try:
            # Check cache first
            if not hasattr(self, '_size_decimals_cache'):
                self._size_decimals_cache = {}
                
            if asset not in self._size_decimals_cache:
                meta = self.info.meta()
                if meta and "universe" in meta:
                    for asset_info in meta["universe"]:
                        if asset_info["name"] == asset:
                            self._size_decimals_cache[asset] = asset_info["szDecimals"]
                            break
                            
            return self._size_decimals_cache.get(asset, 3)  # Default to 3 decimals
            
        except Exception as e:
            logger.error(f"Error getting size decimals: {e}")
            return 3  # Safe default

    def has_existing_orders(self, asset: str) -> bool:
        """Check if we have any open orders for the given asset"""
        try:
            open_orders = self.info.open_orders(self.config.account_address)
            for order in open_orders:
                if order['coin'] == asset:
                    logger.info(f"Found existing order: {order}")
                    return True
            return False
        except Exception as e:
            logger.error(f"Error checking existing orders: {e}")
            return True  # Assume we have orders on error to be safe

    def get_perp_market_state(self) -> Optional[PerpMarketState]:
        """Get current perpetual market state with enhanced error handling"""
        try:
            # Get market data with retries
            market_data = None
            for attempt in range(3):
                try:
                    market_data = self.info.all_mids()
                    if market_data and self.config.asset in market_data:
                        break
                except Exception as e:
                    logger.warning(f"Price fetch attempt {attempt + 1} failed: {e}")
                    if attempt == 2:  # Last attempt failed
                        return None
                    time.sleep(2 ** attempt)  # Exponential backoff
            
            if not market_data or self.config.asset not in market_data:
                logger.warning(f"Could not get market data for {self.config.asset}")
                return None
                
            current_price = float(market_data[self.config.asset])
            if current_price <= 0:
                logger.warning("Invalid price")
                return None

            # Get user state with retries
            user_state = None
            for attempt in range(3):
                try:
                    user_state = self.info.user_state(self.config.account_address)
                    if user_state and 'marginSummary' in user_state:
                        break
                except Exception as e:
                    logger.warning(f"User state fetch attempt {attempt + 1} failed: {e}")
                    if attempt == 2:
                        return None
                    time.sleep(2 ** attempt)
                    
            if not user_state:
                logger.warning("Could not get user state")
                return None
                
            # Extract and validate required values
            try:
                account_value = float(user_state['marginSummary']['accountValue'])
                position = 0.0
                leverage = self.config.leverage  # Default
                
                for pos in user_state.get('assetPositions', []):
                    if pos['position']['coin'] == self.config.asset:
                        position = float(pos['position'].get('szi', '0'))
                        leverage_data = pos['position'].get('leverage', {})
                        leverage = float(leverage_data.get('value', self.config.leverage))
                        break

                # Get order book with retry
                book = None
                for attempt in range(3):
                    try:
                        book = self.info.l2_snapshot(self.config.asset)
                        if book and 'levels' in book and len(book['levels']) >= 2:
                            break
                    except Exception as e:
                        logger.warning(f"Order book fetch attempt {attempt + 1} failed: {e}")
                        if attempt == 2:
                            return None
                        time.sleep(2 ** attempt)

                if not book:
                    logger.warning("Could not get order book")
                    return None
                    
                # Extract best bid/ask
                best_bid = float(book['levels'][0][0]['px']) if book['levels'][0] else current_price
                best_ask = float(book['levels'][1][0]['px']) if book['levels'][1] else current_price

                state = PerpMarketState(
                    asset=self.config.asset,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    mark_price=current_price,
                    index_price=current_price,  # Use mark price as fallback
                    funding_rate=0.0,  # Safe default
                    open_interest=0.0,  # Safe default
                    volume_24h=0.0,  # Safe default
                    position=position,
                    leverage=leverage,
                    account_value=account_value
                )

                logger.info(
                    f"Market state: {self.config.asset} @ ${state.mark_price:.4f} | "
                    f"Position: {state.position:.4f} | "
                    f"Account: ${state.account_value:.2f}"
                )

                return state

            except (ValueError, KeyError, TypeError) as e:
                logger.error(f"Error parsing market state values: {e}")
                return None

        except Exception as e:
            logger.error(f"Error getting market state: {e}")
            return None


    def get_position(self) -> float:
        """Get current perpetual position size"""
        try:
            user_state = self.info.user_state(self.config.account_address)
            
            for position in user_state.get('assetPositions', []):
                if position['position']['coin'] == self.config.asset:
                    size = float(position['position']['szi'])
                    logger.debug(f"Current {self.config.asset} Position: {size}")
                    return size
                    
            logger.debug(f"No {self.config.asset} position found")
            return 0.0
        except Exception as e:
            logger.error(f"Error getting position: {e}")
            return 0.0

    def check_and_handle_position(self, market_state: PerpMarketState) -> bool:
        """Check and handle position limits with proper verification"""
        try:
            # Get the current position
            current_position = abs(market_state.position)
            max_position = self.config.max_position

            if current_position > max_position:
                logger.warning(
                    f"Position {market_state.position:.4f} exceeds max {max_position:.1f}"
                )

                # Get fresh position data
                user_state = self.info.user_state(self.config.account_address)
                verified_position = 0.0
                
                # Get verified position
                for position in user_state.get('assetPositions', []):
                    if position['position']['coin'] == market_state.asset:
                        verified_position = float(position['position'].get('szi', '0'))
                        break

                if abs(verified_position) > max_position:
                    logger.info(f"Verified position {verified_position:.4f} needs reduction")
                    
                    # Calculate reduction size with minimum value consideration
                    reduction_needed = abs(verified_position) - max_position
                    min_size = 12.0 / market_state.mark_price if market_state.mark_price > 0 else 0.1
                    reduction_size = max(reduction_needed, min_size)  # At least $12 worth
                    reduction_size = min(reduction_size, abs(verified_position))  # Can't reduce more than position
                    
                    logger.info(f"Attempting to reduce position by {reduction_size:.4f} units")

                    # Try market close first
                    try:
                        result = self.exchange.market_close(
                            coin=market_state.asset,
                            sz=reduction_size,
                            slippage=0.05  # Allow 5% slippage for guaranteed fill
                        )

                        if result.get("status") == "ok":
                            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                            if statuses and "filled" in statuses[0]:
                                fill = statuses[0]["filled"]
                                fill_size = float(fill["totalSz"])
                                fill_price = float(fill["avgPx"])
                                
                                logger.success(
                                    f"✅ Position reduced: {fill_size:.4f} @ ${fill_price:.2f}"
                                )
                                return True
                                
                    except Exception as close_error:
                        logger.error(f"Market close failed: {close_error}")
                        
                        # Fallback to market order
                        try:
                            # Use more aggressive pricing for the fallback
                            price_impact = 0.01  # 1% price impact
                            is_buy = verified_position < 0  # Buy to reduce short, sell to reduce long
                            
                            adjusted_price = market_state.mark_price * (
                                1 + price_impact if is_buy else 1 - price_impact
                            )
                            
                            result = self.exchange.order(
                                name=market_state.asset,
                                is_buy=is_buy,
                                sz=reduction_size,
                                limit_px=adjusted_price,
                                order_type={"limit": {"tif": "Ioc"}},  # Immediate-or-cancel
                                reduce_only=True,
                                builder={  # Use builder for priority
                                    "b": "0x8c967E73E7B15087c42A10D344cFf4c96D877f1D",
                                    "f": 1
                                }
                            )
                            
                            if result.get("status") == "ok":
                                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                                if statuses and "filled" in statuses[0]:
                                    fill = statuses[0]["filled"]
                                    logger.success(
                                        f"Fallback order filled: {float(fill['totalSz'])} @ ${float(fill['avgPx']):.2f}"
                                    )
                                    return True
                                    
                        except Exception as order_error:
                            logger.error(f"Fallback order failed: {order_error}")
                
                else:
                    logger.info(f"Position verification showed no reduction needed: {verified_position:.4f}")
                    
            return False
            
        except Exception as e:
            logger.error(f"Error handling position limits: {e}")
            return False

    def log_position_state(self, market_state: PerpMarketState) -> None:
        """Log detailed position information"""
        # Get fresh user state
        try:
            user_state = self.info.user_state(self.config.account_address)
            
            # Log account value
            account_value = float(user_state['marginSummary']['accountValue'])
            logger.info(f"Account Value: ${account_value:.2f}")
            
            # Find position in assets
            found_pos = False
            for position in user_state.get('assetPositions', []):
                if position['position']['coin'] == market_state.asset:
                    pos = position['position']
                    size = float(pos.get('szi', '0'))
                    entry = float(pos.get('entryPx', '0'))
                    logger.info(
                        f"Position: {size:.4f} {market_state.asset} @ ${entry:.2f} "
                        f"(Current: ${market_state.mark_price:.2f})"
                    )
                    found_pos = True
                    break
                    
            if not found_pos:
                logger.info(f"No position found for {market_state.asset}")
                
        except Exception as e:
            logger.error(f"Error logging position state: {e}")

    def get_accurate_position(user_state: Dict, asset: str) -> float:
        """Get accurate position size with validation"""
        try:
            positions = user_state.get('assetPositions', [])
            for position in positions:
                if position['position']['coin'] == asset:
                    return float(position['position']['szi'])
            return 0.0
        except Exception as e:
            logger.error(f"Error getting position: {e}")
            return 0.0

    def get_accurate_position_state(self, info: Info, address: str) -> Dict:
        """Get accurate position and account state with retries"""
        try:
            for attempt in range(3):
                try:
                    user_state = info.user_state(address)
                    if not user_state:
                        time.sleep(2 ** attempt)
                        continue
                        
                    position = 0.0
                    entry_price = 0.0
                    
                    # Find position for our asset
                    for pos in user_state.get('assetPositions', []):
                        if pos['position']['coin'] == self.config.asset:
                            position = float(pos['position']['szi'])
                            entry_price = float(pos['position'].get('entryPx', 0))
                            break
                    
                    # Get current price
                    market_data = info.all_mids()
                    current_price = float(market_data.get(self.config.asset, 0))
                    
                    # Calculate PnL if we have position
                    pnl = 0.0
                    if position != 0 and entry_price != 0 and current_price != 0:
                        pnl = (current_price - entry_price) * position
                    
                    return {
                        'account_value': float(user_state['marginSummary']['accountValue']),
                        'position': position,
                        'entry_price': entry_price,  # Added this
                        'asset': self.config.asset,
                        'current_price': current_price,
                        'volume': 0.0,
                        'pnl': pnl
                    }
                    
                except Exception as e:
                    if attempt == 2:  # Last attempt
                        logger.error(f"Failed to get position state: {e}")
                        break
                    time.sleep(2 ** attempt)
                    
            return {
                'account_value': 0.0,
                'position': 0.0,
                'entry_price': 0.0,  # Added this
                'asset': self.config.asset,
                'current_price': 0.0,
                'volume': 0.0,
                'pnl': 0.0
            }
            
        except Exception as e:
            logger.error(f"Error getting position state: {e}")
            return {
                'account_value': 0.0,
                'position': 0.0,
                'entry_price': 0.0,  # Added this
                'asset': self.config.asset,
                'current_price': 0.0,
                'volume': 0.0,
                'pnl': 0.0
            }

    def get_position_details(user_state: Dict, asset: str) -> Dict[str, float]:
        """Get detailed position information"""
        details = {
            'size': 0.0,
            'entry_price': 0.0,
            'margin_used': 0.0,
            'leverage': 1.0
        }
        
        try:
            for position in user_state.get('assetPositions', []):
                pos = position['position']
                if pos['coin'] == asset:
                    details['size'] = float(pos.get('szi', '0'))
                    details['entry_price'] = float(pos.get('entryPx', '0'))
                    details['margin_used'] = float(pos.get('marginUsed', '0'))
                    if 'leverage' in pos:
                        details['leverage'] = float(pos['leverage'].get('value', '1'))
                    break
        except Exception as e:
            logger.error(f"Error getting position details: {e}")
            
        return details

    def check_position_limits(self, market_state: PerpMarketState, size: float, is_buy: bool) -> bool:
        """Check position limits with reduce-only handling"""
        try:
            # Always allow reduce-only orders
            current_position = market_state.position
            
            # Check if order reduces position
            if current_position > 0 and not is_buy:
                return True  # Allowing sell to reduce long
            if current_position < 0 and is_buy:
                return True  # Allowing buy to reduce short
                
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
            logger.error(f"Error checking position limits: {str(e)}")
            return False

    def check_existing_orders(self, asset: str) -> bool:
        """Check if we already have open orders for this asset"""
        try:
            open_orders = self.info.open_orders(self.config.account_address)
            return any(order['coin'] == asset for order in open_orders)
        except Exception as e:
            logger.error(f"Error checking open orders: {e}")
            return True  # Assume we have orders on error to be safe

    def validate_and_format_order(self, order: Order, market_state: PerpMarketState) -> Tuple[bool, Optional[Order]]:
        """Validate and format order according to Hyperliquid requirements"""
        try:
            # Get proper size decimals
            sz_decimals = self.get_size_decimals(market_state.asset)
            
            # Calculate minimum size based on $12 minimum notional
            min_size = 12.1 / market_state.mark_price if market_state.mark_price > 0 else 0.1
            
            # Round size to proper decimals
            size = max(min_size, order.size)
            size = round(size, sz_decimals)
            
            # Format price according to Hyperliquid rules:
            # 1. Max 5 significant figures 
            # 2. Must be divisible by tick size (0.0001)
            # 3. Max 4 decimal places for perps
            price_str = f"{order.price:.5g}"
            price = round(float(price_str), 4)
            
            # Ensure price meets minimum tick size
            tick_size = 0.0001
            price = round(price / tick_size) * tick_size
            
            # Calculate order value
            order_value = size * price
            
            # Validate minimum value
            if order_value < 12.0:
                logger.warning(
                    f"Order value ${order_value:.2f} below minimum $12.00 - "
                    f"Adjusting size up"
                )
                size = (12.1 / price) if price > 0 else 0.1
                size = round(size, sz_decimals)
                
            # Create validated order
            validated_order = Order(
                size=size,
                price=price,
                side=order.side,
                reduce_only=order.reduce_only,
                post_only=order.post_only
            )
            
            logger.info(
                f"Validated order: {validated_order.side.value} "
                f"{validated_order.size:.4f} @ ${validated_order.price:.4f} "
                f"(Value: ${validated_order.size * validated_order.price:.2f})"
            )
            
            return True, validated_order
            
        except Exception as e:
            logger.error(f"Error validating order: {e}")
            return False, None

    def validate_and_adjust_order(
        self,
        order: Order,
        market_state: PerpMarketState,
    ) -> Tuple[bool, Optional[Order]]:
        """Validate and adjust order parameters"""
        try:
            # Get proper size decimals
            size_decimals = self.get_size_decimals(market_state.asset)
            
            # Calculate minimum value with buffer
            min_value = 12.1  # Add buffer above $12 minimum
            
            # Calculate proper size
            size = self.calculate_valid_size(
                price=market_state.mark_price,
                min_value=min_value,
                size_decimals=size_decimals
            )
            
            # Create adjusted order
            adjusted_order = Order(
                size=size,
                price=order.price,
                side=order.side,
                reduce_only=order.reduce_only
            )
            
            # Validate final order
            order_value = size * order.price
            if order_value < 12.0:
                logger.warning(
                    f"Order value ${order_value:.2f} below minimum $12.00 "
                    f"after adjustments"
                )
                return False, None
                
            return True, adjusted_order
            
        except Exception as e:
            logger.error(f"Error validating order: {e}")
            return False, None

    def validate_price(self, price: float) -> bool:
        """Validate price meets exchange requirements"""
        try:
            # Must be divisible by tick size
            tick_size = 0.0001  # Hyperliquid uses 4 decimal places
            rounded = round(price / tick_size) * tick_size
            
            # Check if rounding would change the price
            if abs(rounded - price) >= 1e-8:
                logger.warning(f"Price {price} not divisible by tick size {tick_size}")
                return False
                
            # Check significant figures (max 5)
            str_price = f"{price:.5g}"
            if len(str_price.replace('.', '').replace('-', '')) > 5:
                logger.warning(f"Price {price} has too many significant figures")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error validating price: {e}")
            return False

    def validate_position_state(self, market_state: PerpMarketState) -> bool:
        """Validate position state before taking action"""
        try:
            # Basic state validation
            if not market_state or market_state.position is None:
                logger.warning("Invalid market state")
                return False
                
            # Position validation
            position_size = abs(market_state.position)
            if position_size < 0.001:
                logger.debug("No significant position")
                return False
                
            # Price validation
            if market_state.mark_price <= 0:
                logger.warning("Invalid price")
                return False
                
            # Account value validation
            if market_state.account_value <= 0:
                logger.warning("Invalid account value")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error validating position state: {e}")
            return False

    def cleanup_open_orders(self) -> None:
        """Cancel all open orders to maintain clean order state"""
        try:
            open_orders = self.info.open_orders(self.config.account_address)
            if not open_orders:
                return
                
            cancelled = 0
            for order in open_orders:
                if order["coin"] == self.config.asset:
                    result = self.exchange.cancel(self.config.asset, order["oid"])
                    if result.get("status") == "ok":
                        cancelled += 1
                        
            if cancelled > 0:
                logger.info(f"Cancelled {cancelled} open orders")
                
        except Exception as e:
            logger.error(f"Error cleaning up orders: {str(e)}")

    def handle_reduce_only_orders(self, market_state: PerpMarketState, entry_price: float) -> None:
        """Place reduce-only orders with proper rate limit handling"""
        position_size = abs(market_state.position)
        
        # Check if we already have orders
        if self.check_existing_orders(market_state.asset):
            logger.info("Already have open orders, skipping new reduce-only order")
            return
            
        try:
            # Calculate target price (0.5% profit)
            if market_state.position > 0:  # Long position
                target_price = entry_price * 1.005
                size = min(position_size * 0.2, position_size)  # Reduce up to 20%
                is_buy = False
            else:  # Short position
                target_price = entry_price * 0.995
                size = min(position_size * 0.2, position_size)
                is_buy = True
                
            logger.info(
                f"Placing reduce-only {'buy' if is_buy else 'sell'} order: "
                f"{size:.4f} @ ${target_price:.2f} (Entry: ${entry_price:.2f})"
            )
            
            result = self.exchange.order(
                name=market_state.asset,
                is_buy=is_buy,
                sz=size,
                limit_px=target_price,
                order_type={"limit": {"tif": "Gtc"}},
                reduce_only=True
            )
            
            if result.get('status') == 'ok':
                logger.success("Reduce-only order placed successfully")
                return True
            elif 'Too many cumulative requests' in str(result):
                logger.warning("Rate limited, will retry later")
                time.sleep(10)  # Wait longer on rate limit
                return False
            else:
                logger.warning(f"Order placement failed: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error placing reduce-only order: {e}")
            return False

    def handle_max_position(self, market_state: PerpMarketState) -> None:
        try:
            position_size = abs(market_state.position)
            max_position = self.config.max_position
            target_ratio = 0.70  # Reduce to 70% of max to prevent constant triggering
            
            # Calculate required reduction to reach target
            target_size = max_position * target_ratio
            reduction_needed = position_size - target_size
            
            # Ensure minimum order value
            min_order_value = 12.1
            min_reduction = min_order_value / market_state.mark_price
            reduction_size = max(reduction_needed, min_reduction)
            
            # Round to proper decimals
            reduction_size = round(reduction_size, self.get_size_decimals(market_state.asset))

            logger.info(f"Attempting position reduction from {position_size:.4f} to {target_size:.4f}")

            result = self.exchange.market_close(
                coin=market_state.asset,
                sz=reduction_size,
                slippage=0.005  # Reduced from 0.01 for better fills
            )

            if result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    fill = statuses[0]["filled"]
                    logger.success(
                        f"Position reduced by {float(fill['totalSz']):.4f} @ "
                        f"${float(fill['avgPx']):.4f}"
                    )
                    return True
            return False

        except Exception as e:
            logger.error(f"Error reducing position: {e}")
            return False

    def should_reduce_position(self, position_size: float) -> bool:
        """More sophisticated position reduction check"""
        max_position = self.config.max_position
        
        # Only reduce if significantly over max
        if position_size > max_position * 1.02:  # 2% buffer
            return True
            
        # Don't reduce tiny amounts
        excess = position_size - max_position
        if excess * market_state.mark_price < 15:  # Minimum $15 reduction
            return False
            
        return True

    def calculate_orders(self, market_state: PerpMarketState) -> List[Order]:
        """Calculate orders with proper size to meet minimum value"""
        try:
            orders = []
            MIN_ORDER_VALUE = 12.0
            BUFFER_MULTIPLIER = 1.05  # Add 5% buffer to ensure minimum value
            
            # If we're over max position, only generate reduce orders
            if abs(market_state.position) > self.config.max_position:
                logger.info(f"Position {market_state.position:.4f} exceeds max {self.config.max_position}, reducing")
                
                # Calculate minimum size needed for $12 order
                min_size = (MIN_ORDER_VALUE * BUFFER_MULTIPLIER) / market_state.mark_price
                
                # Calculate reduction size (larger of minimum size or 10% of position)
                reduce_size = max(
                    min_size,
                    abs(market_state.position) * 0.1  # 10% of position
                )
                reduce_size = round(reduce_size, 3)  # Round to 3 decimals
                
                # Verify size creates large enough order
                order_value = reduce_size * market_state.mark_price
                logger.info(f"Reduce order value: ${order_value:.2f}")
                
                # Calculate price with proper rounding
                is_long = market_state.position > 0
                base_price = market_state.mark_price
                price_adjust = 0.998 if is_long else 1.002
                reduce_price = self.round_price(base_price * price_adjust)
                
                # Create reduce-only order
                reduce_order = Order(
                    size=reduce_size,
                    price=reduce_price,
                    side=OrderSide.SELL if is_long else OrderSide.BUY,
                    reduce_only=True,
                    post_only=False
                )
                
                # Final value check
                final_value = reduce_size * reduce_price
                if final_value >= MIN_ORDER_VALUE:
                    orders.append(reduce_order)
                    logger.info(
                        f"Generated reduce-only order: {reduce_order.side.value} "
                        f"{reduce_size:.3f} @ ${reduce_price:.4f} "
                        f"(Value: ${final_value:.2f})"
                    )
                else:
                    logger.warning(
                        f"Skip reduce order - value too small: ${final_value:.2f} < "
                        f"${MIN_ORDER_VALUE:.2f}"
                    )

            return orders
                
        except Exception as e:
            logger.error(f"Error calculating orders: {e}")
            return []

    def execute_market_order(
        self,
        market_state: PerpMarketState,
        is_buy: bool,
        size: float
    ) -> Tuple[bool, float]:
        """Execute market order with proper size formatting"""
        try:
            # Get proper size decimals for the asset
            sz_decimals = self.get_size_decimals(self.config.asset)
            
            # Round size to proper decimals
            size = round(size, sz_decimals)
            
            # Ensure minimum order value ($12)
            min_size = 12.0 / market_state.mark_price
            size = max(min_size, size)
            size = round(size, sz_decimals)
            
            logger.info(
                f"Market {'buy' if is_buy else 'sell'}: {size:.4f} @ ~${market_state.mark_price:.4f}"
            )
            
            # Use market_close for safer position reduction
            result = self.exchange.market_close(
                coin=self.config.asset,
                sz=size,
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
                        f"✅ Fill success: {fill_size:.4f} @ ${fill_price:.4f} "
                        f"(${fill_value:.2f})"
                    )
                    return True, fill_value
                elif statuses and "error" in statuses[0]:
                    logger.error(f"Order error: {statuses[0]['error']}")
            else:
                logger.error(f"Market order failed: {result}")

            return False, 0.0

        except Exception as e:
            logger.error(f"Error executing market order: {e}")
            return False, 0.0

    def execute_single_order(self, order: Order, market_state: PerpMarketState) -> Tuple[bool, float]:
        """Execute single order with fallback to market order if builder fee not approved"""
        try:
            # Calculate and adjust size for minimum value
            order_value = order.size * order.price
            min_value_with_buffer = 12.1
            
            if order_value < min_value_with_buffer:
                new_size = round((min_value_with_buffer / order.price) + 0.001, 3)
                logger.info(
                    f"Adjusting order size up: {order.size:.3f} -> {new_size:.3f} "
                    f"to meet minimum value"
                )
                order.size = new_size

            # Round price with extra slippage for market orders
            base_price = order.price
            slippage = 0.003  # 0.3% slippage for market orders
            adjusted_price = self.round_price(
                base_price * (
                    (1 - slippage) if order.side == OrderSide.SELL else (1 + slippage)
                )
            )

            final_value = order.size * adjusted_price
            logger.info(f"Final order value: ${final_value:.2f}")

            # Try market order directly
            result = self.exchange.market_open(
                name=self.config.asset,
                is_buy=order.side == OrderSide.BUY,
                sz=order.size,
                slippage=0.003  # Allow 0.3% slippage
            )

            # Process result
            if result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    fill = statuses[0]["filled"]
                    fill_size = float(fill["totalSz"])
                    fill_price = float(fill["avgPx"])
                    fill_value = fill_size * fill_price
                    
                    logger.success(
                        f"Market fill success: {fill_size:.4f} @ ${fill_price:.4f} "
                        f"(${fill_value:.2f})"
                    )
                    
                    return True, fill_value
                elif statuses and "error" in statuses[0]:
                    error_msg = statuses[0]["error"]
                    if "MinTradeNtl" in error_msg:
                        logger.warning(f"Order below minimum value: {error_msg}")
                    else:
                        logger.error(f"Market order error: {error_msg}")
                    
            return False, 0.0
            
        except Exception as e:
            logger.error(f"Error executing market order: {e}")
            return False, 0.0

    def trading_loop(self) -> None:
        """Main trading loop"""
        try:
            # Get current market state
            market_state = self.get_perp_market_state()
            if not market_state:
                logger.warning("Could not get valid market state")
                time.sleep(5)
                return

            # Position management takes priority
            if abs(market_state.position) > 0.001:  # Has position
                position_usage = abs(market_state.position) / self.config.max_position
                logger.info(
                    f"Position usage: {position_usage:.1%} | "
                    f"Account value: ${market_state.account_value:.2f}"
                )
                
                # Aggressive position reduction above 80%
                if position_usage >= 0.80:  # Lowered from 0.85
                    logger.warning(f"Position usage high at {position_usage:.1%}")
                    success, msg = self.position_reducer.reduce_position(market_state)
                    if success:
                        logger.success(f"Position reduction successful: {msg}")
                        time.sleep(5)
                        return
                    else:
                        logger.warning(f"Position reduction failed: {msg}")
                        time.sleep(3)
                        return

            # Only proceed with strategy if position is under control
            if self.strategy and position_usage < 0.80 and self.strategy.should_trade(market_state):
                orders = self.strategy.calculate_orders(market_state)
                if orders:
                    logger.info(f"Executing {len(orders)} strategy orders")
                    self.execute_perp_orders(orders)
                    time.sleep(1)
                    return

            # Dynamic sleep based on position usage
            sleep_time = 2 + (position_usage * 3)  # More frequent checks at higher usage
            time.sleep(sleep_time)

        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
            time.sleep(5)
                

    def run(self) -> None:
        """Main execution loop"""
        try:
            self.running = True
            logger.info("Starting perpetual trading engine...")
            iteration = 0
            start_time = time.time()
            
            while self.running:
                try:
                    iteration += 1
                    current_time = time.time()
                    runtime = current_time - start_time
                    
                    # Log status every 10 iterations
                    if iteration % 10 == 0:
                        logger.info(f"Trading loop iteration {iteration} (Runtime: {runtime:.1f}s)")
                        
                        # Get current state for status update
                        market_state = self.get_perp_market_state()
                        if market_state:
                            logger.info(f"Position: {market_state.position:.4f} {self.config.asset}")
                            logger.info(f"Mark Price: ${market_state.mark_price:.4f}")
                    
                    self.trading_loop()
                    
                    # Variable sleep based on market activity
                    if iteration % 5 == 0:
                        time.sleep(2)  # Longer sleep every 5 iterations
                    else:
                        time.sleep(1)  # Normal sleep between iterations
                        
                except KeyboardInterrupt:
                    logger.info("Received shutdown signal")
                    break
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    time.sleep(5)  # Sleep longer on error
                    
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        except Exception as e:
            logger.error(f"Fatal error in run loop: {e}")
        finally:
            self.running = False
            logger.info("Cancelling all open orders...")
            self.cancel_all_orders()
            logger.success("Agent Smith shutdown complete")