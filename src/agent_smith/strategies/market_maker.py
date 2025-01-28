from typing import List, Optional, Tuple
from loguru import logger
import math
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import random

from agent_smith.strategies.base import PerpStrategy
from agent_smith.trading_types import PerpMarketState, Order, OrderSide
from agent_smith.config import TradingConfig

class AggressiveMarketMaker(PerpStrategy):
    def __init__(
        self,
        config: TradingConfig,
        min_spread: float = 0.002,  # 0.2% minimum spread
        base_position: float = 0.25,  # Smaller base position
        max_position: float = 5.0,
        min_order_interval: int = 60,  # 60s between orders
        profit_take_threshold: float = 0.012,  # 1.2% profit target
        stop_loss_threshold: float = 0.015,  # 1.5% stop loss
        volatility_window: int = 50,
        momentum_window: int = 20,
        momentum_threshold: float = 0.003,  # 0.3% momentum trigger
        min_notional: float = 12.0,
        min_size: float = 0.01
    ):
        super().__init__(config)
        self.min_spread = min_spread
        self.base_position = base_position
        self.max_position = max_position
        self.min_order_interval = min_order_interval
        self.profit_take_threshold = profit_take_threshold
        self.stop_loss_threshold = stop_loss_threshold
        self.volatility_window = volatility_window
        self.min_notional = min_notional
        self.min_size = min_size
        
        # Momentum parameters
        self.momentum_window = momentum_window
        self.momentum_threshold = momentum_threshold
        self.momentum_prices = []
        self.last_momentum_signal = None
        self.momentum_trades = 0
        self.max_momentum_trades = 2  # Max 2 momentum trades per hour
        self.momentum_reset_time = datetime.now()
        
        # Trading state
        self.price_history = []
        self.last_order_time = datetime.now() - timedelta(minutes=5)
        self.base_volatility = None
        self.position_entry_price = None
        self.current_position = 0
        self.trade_history = []
        
        # Profitability tracking
        self.total_pnl = 0.0
        self.trades_since_last_profit = 0
        self.max_losing_trades = 3  # Reset after 3 losses# Reset strategy after 3 consecutive losses

    def calculate_market_momentum(self, mark_price: float, best_bid: float, best_ask: float) -> Optional[str]:
        """Calculate momentum signal with improved direction detection"""
        try:
            self.momentum_prices.append(mark_price)
            if len(self.momentum_prices) > self.momentum_window:
                self.momentum_prices.pop(0)
                
            if len(self.momentum_prices) < self.momentum_window:
                return None
                
            prices = pd.Series(self.momentum_prices)
            
            # Calculate multiple timeframe EMAs
            short_window = self.momentum_window // 4  # 5-period
            medium_window = self.momentum_window // 2  # 10-period
            long_window = self.momentum_window  # 20-period
            
            short_ema = prices.ewm(span=short_window).mean().iloc[-1]
            medium_ema = prices.ewm(span=medium_window).mean().iloc[-1]
            long_ema = prices.ewm(span=long_window).mean().iloc[-1]
            
            # Calculate RSI
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            # Mean reversion check
            price_std = prices.std()
            zscore = (mark_price - prices.mean()) / price_std if price_std > 0 else 0
            
            # Calculate order book imbalance
            mid_price = (best_bid + best_ask) / 2
            book_imbalance = (mark_price - mid_price) / mid_price if mid_price > 0 else 0
            
            # Combined signal
            signal_strength = 0.0
            
            # Trend following signals (40% weight)
            if short_ema > medium_ema > long_ema:
                signal_strength += 0.4
            elif short_ema < medium_ema < long_ema:
                signal_strength -= 0.4
                
            # Mean reversion signals (30% weight)
            if zscore < -2:  # Oversold
                signal_strength += 0.3
            elif zscore > 2:  # Overbought
                signal_strength -= 0.3
                
            # RSI signals (20% weight)
            if rsi < 30:
                signal_strength += 0.2
            elif rsi > 70:
                signal_strength -= 0.2
                
            # Order book imbalance (10% weight)
            signal_strength += book_imbalance * 0.1
            
            # Determine final signal with stronger thresholds
            if signal_strength > 0.3:  # Stronger threshold for long
                return "long"
            elif signal_strength < -0.3:  # Stronger threshold for short
                return "short"
                
            return None
            
        except Exception as e:
            logger.error(f"Error calculating momentum: {e}")
            return None

    def calculate_spread_thresholds(self, market_state: PerpMarketState) -> float:
        """Calculate dynamic spread thresholds based on market conditions"""
        try:
            # Base spread threshold - lowered to 0.04% (4 bps)
            base_threshold = 0.0004
            
            # Check current position utilization
            position_usage = abs(market_state.position) / self.config.max_position
            
            # Simpler threshold adjustment
            if position_usage > 0.8:
                # Much more aggressive when needing to reduce
                return 0.0002  # 2 bps when position is high
            elif position_usage < 0.3:
                # More aggressive when building
                return 0.0003  # 3 bps when position is low
                
            return base_threshold
            
        except Exception as e:
            logger.error(f"Error calculating spread threshold: {e}")
            return 0.0004  # Safe default of 4 bps

    def calculate_position_size(self, market_state: PerpMarketState, signal_strength: float) -> float:
        """Calculate dynamic position size based on signal strength and risk"""
        try:
            # Start with minimum size to meet $12 notional
            min_size = 12.1 / market_state.mark_price
            
            # Scale size based on signal strength (0.3 to 1.0)
            size_scalar = min(1.0, max(0.3, abs(signal_strength)))
            
            # Account for position limits
            max_position_remaining = self.max_position - abs(market_state.position)
            if max_position_remaining <= 0:
                return 0
                
            # Calculate size considering remaining capacity
            base_size = min(min_size * 1.5 * size_scalar, max_position_remaining * 0.2)
            
            # Risk-based size adjustment
            position_utilization = abs(market_state.position) / self.max_position
            risk_scalar = 1.0 - position_utilization  # Reduce size as position grows
            
            # Account volatility adjustment
            if len(self.momentum_prices) >= 20:
                volatility = np.std(self.momentum_prices[-20:])
                avg_price = np.mean(self.momentum_prices[-20:])
                vol_ratio = volatility / avg_price if avg_price > 0 else 0
                vol_scalar = max(0.5, 1.0 - (vol_ratio * 10))  # Reduce size in high vol
            else:
                vol_scalar = 0.75  # Conservative when lacking data
                
            # Final size calculation
            size = base_size * risk_scalar * vol_scalar
            
            # Round to proper decimals
            decimals = self.get_size_decimals(market_state.asset)
            size = round(size, decimals)
            
            # Ensure minimum order size
            return max(min_size, size)
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return min_size  # Return minimum size on error

    def validate_trade(self, order: Order, market_state: PerpMarketState) -> bool:
        """Enhanced trade validation with risk checks"""
        try:
            # Check minimum order value 
            order_value = order.size * market_state.mark_price
            if order_value < 12.0:
                logger.warning(f"Order value ${order_value:.2f} below minimum $12.00")
                return False
                
            # Check maximum position size
            new_position = market_state.position
            if order.side == OrderSide.BUY:
                new_position += order.size
            else:
                new_position -= order.size
                
            if abs(new_position) > self.max_position:
                logger.warning(f"New position {new_position:.4f} would exceed max {self.max_position}")
                return False
                
            # Check recent performance
            if len(self.trade_history) >= 3:
                recent_trades = self.trade_history[-3:]
                losing_trades = sum(1 for t in recent_trades if t['pnl'] < 0)
                if losing_trades >= 2:
                    logger.warning("Too many recent losses - skipping trade")
                    return False
                    
            # Momentum confirmation
            momentum = self.calculate_market_momentum(
                market_state.mark_price,
                market_state.best_bid, 
                market_state.best_ask
            )
            
            if momentum is None:
                logger.info("No clear momentum signal")
                return False
                
            # Direction check
            if (momentum == "long" and order.side == OrderSide.SELL) or \
            (momentum == "short" and order.side == OrderSide.BUY):
                logger.warning("Order direction conflicts with momentum")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error validating trade: {e}")
            return False

    def should_trade(self, market_state: PerpMarketState) -> bool:
        """Enhanced trade entry conditions"""
        try:
            # Check spread
            spread = (market_state.best_ask - market_state.best_bid) / market_state.best_bid
            threshold = self.calculate_spread_thresholds(market_state)
            
            if spread < threshold:
                return False
                
            # Check recent trades
            if len(self.trade_history) >= 2:
                last_trades = self.trade_history[-2:]
                if all(t['pnl'] < 0 for t in last_trades):
                    logger.warning("Multiple consecutive losses - pausing trading")
                    return False
                    
            # Check volatility
            if len(self.momentum_prices) >= 20:
                volatility = np.std(self.momentum_prices[-20:])
                avg_price = np.mean(self.momentum_prices[-20:])
                vol_ratio = volatility / avg_price if avg_price > 0 else 0
                
                if vol_ratio > 0.005:  # 0.5% volatility threshold
                    logger.info(f"High volatility ({vol_ratio:.3%}) - waiting for calmer market")
                    return False
                    
            return True
            
        except Exception as e:
            logger.error(f"Error in should_trade: {e}")
            return False

    def calculate_optimal_size(self, mark_price: float) -> float:
        """Calculate optimal order size based on position and conditions"""
        try:
            # Calculate minimum size for $12 notional
            min_size = 12.1 / mark_price if mark_price > 0 else 0.1
            
            # Add 20% buffer to ensure we clear minimum
            base_size = min_size * 1.2
            
            # Round to appropriate decimals
            size = round(base_size, self.get_size_decimals(self.config.asset))
            
            # Ensure minimum size
            return max(size, 0.001)  # At least 0.001 units
            
        except Exception as e:
            logger.error(f"Error calculating size: {e}")
            return 0.001  # Safe minimum

    def calculate_market_momentum(self, mark_price: float, best_bid: float, best_ask: float) -> Optional[float]:
        """Calculate momentum signal using multiple indicators"""
        self.momentum_prices.append(mark_price)  # Use mark_price instead of undefined price
        if len(self.momentum_prices) > self.momentum_window:
            self.momentum_prices.pop(0)
            
        if len(self.momentum_prices) < self.momentum_window:
            return None
            
        # Calculate EMAs
        prices = pd.Series(self.momentum_prices)
        
        fast_window = self.momentum_window // 4
        slow_window = self.momentum_window
        
        fast_ema = prices.ewm(span=fast_window).mean().iloc[-1]
        slow_ema = prices.ewm(span=slow_window).mean().iloc[-1]
        
        # Calculate RSI
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs)).iloc[-1]
        
        # Combine signals
        momentum_ema = (fast_ema / slow_ema - 1)
        rsi_signal = (rsi - 50) / 50  # Normalize RSI to [-1, 1]
        
        # Weighted combination
        momentum = 0.7 * momentum_ema + 0.3 * rsi_signal
        
        return momentum

    def calculate_orders(self, market_state: PerpMarketState) -> List[Order]:
        """Calculate orders with momentum-based sizing"""
        try:
            orders = []
            
            # Calculate base order size
            min_size = self.min_notional / market_state.mark_price if market_state.mark_price > 0 else 0
            base_size = max(min_size * 1.2, self.min_size)
            
            # Increase size for momentum trades
            if self.last_momentum_signal:
                trade_size = base_size * 1.5  # 50% larger for momentum trades
                
                # Determine trade side based on momentum signal
                side = OrderSide.BUY if self.last_momentum_signal == "long" else OrderSide.SELL
                
                # Create market order
                if self.check_position_limits(market_state, trade_size, side == OrderSide.BUY):
                    momentum_order = Order(
                        size=trade_size,
                        price=market_state.mark_price,  # Using mark price for market order
                        side=side,
                        reduce_only=False,
                        post_only=False  # Market order
                    )
                    
                    orders.append(momentum_order)
                    logger.info(f"Generated momentum market {side.value} order: {trade_size:.4f}")
                
                self.last_momentum_signal = None  # Reset signal
                
            else:
                # Market making with simpler approach
                spread = market_state.best_ask - market_state.best_bid
                if spread > 0:
                    # Place market orders if conditions are right
                    if market_state.position + base_size <= self.max_position:
                        orders.append(Order(
                            size=base_size,
                            price=market_state.mark_price,
                            side=OrderSide.BUY,
                            reduce_only=False,
                            post_only=False
                        ))
                    
                    if market_state.position - base_size >= -self.max_position:
                        orders.append(Order(
                            size=base_size,
                            price=market_state.mark_price,
                            side=OrderSide.SELL,
                            reduce_only=False,
                            post_only=False
                        ))
            
            return orders
                
        except Exception as e:
            logger.error(f"Error calculating orders: {e}")
            return []

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

    def execute_position_reduction(self, market_state: PerpMarketState) -> bool:
        """More aggressive position reduction"""
        try:
            reduction_size = 0.57  # Match minimum order size
            
            # Calculate aggressive price with 0.5% slippage
            is_long = market_state.position > 0
            price_impact = 0.005  # 0.5% price impact
            reduce_price = market_state.mark_price * (
                (1 - price_impact) if is_long else (1 + price_impact)
            )
            
            # Use IOC order with builder fee
            result = self.exchange.order(
                name=market_state.asset,
                is_buy=not is_long,  # Opposite of position
                sz=reduction_size,
                limit_px=reduce_price,
                order_type={"limit": {"tif": "Ioc"}},  # Immediate-or-cancel
                reduce_only=True,
                builder={
                    "b": "0x8c967E73E7B15087c42A10D344cFf4c96D877f1D",
                    "f": 1  # Use builder fee
                }
            )

            if result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    fill = statuses[0]["filled"]
                    fill_size = float(fill["totalSz"])
                    fill_price = float(fill["avgPx"])
                    logger.success(
                        f"Position reduced: {fill_size:.4f} @ ${fill_price:.4f}"
                    )
                    return True

            # If IOC fails, try market order
            result = self.exchange.market_close(
                coin=market_state.asset,
                sz=reduction_size,
                slippage=0.01  # 1% slippage
            )
            
            if result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    fill = statuses[0]["filled"]
                    logger.success(
                        f"Position reduced via market: {float(fill['totalSz'])} @ "
                        f"${float(fill['avgPx']):.4f}"
                    )
                    return True

            return False

        except Exception as e:
            logger.error(f"Error reducing position: {e}")
            return False

    def execute_and_verify_order(self, order: Order, market_state: PerpMarketState) -> Tuple[bool, str]:
        """Execute an order and verify its fill status"""
        try:
            # Pre-execution validation
            if not self.validate_order(order, market_state.mark_price):
                return False, "Order validation failed"

            # Get starting fills for comparison
            initial_fills = self.info.user_fills(self.config.account_address)
            initial_fill_count = len(initial_fills) if initial_fills else 0

            # Calculate proper slippage based on order type and market conditions
            slippage = 0.01  # Base 1% slippage
            if order.reduce_only:
                slippage = 0.02  # Higher slippage (2%) for reduce-only orders
            
            # Place market order directly
            logger.info(
                f"Placing market {order.side.value} order: {order.size} {self.config.asset} @ ~${market_state.mark_price:.4f} "
                f"(Slippage: {slippage:.1%})"
            )

            result = self.exchange.market_open(
                name=self.config.asset,
                is_buy=order.side == OrderSide.BUY,
                sz=order.size,
                slippage=slippage
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

                logger.success(
                    f"Order filled: {filled_size} @ ${filled_price:.4f} "
                    f"(Value: ${fill_value:.2f})"
                )
                return True, f"Fill confirmed - ${fill_value:.2f}"
            else:
                logger.warning("No fill detected after order placement")
                return False, "No fill detected"

        except Exception as e:
            logger.error(f"Error executing order: {str(e)}")
            return False, str(e)

    def on_trade_update(self, fill_price: float, fill_size: float, pnl: float) -> None:
        """Handle trade updates and adjust strategy"""
        try:
            if pnl > 0:
                self.trades_since_last_profit = 0
                logger.info("Profitable trade - resetting loss counter")
            else:
                self.trades_since_last_profit += 1
                logger.warning(f"Loss #{self.trades_since_last_profit}")
            
            self.total_pnl += pnl
            
            # Record trade
            self.trade_history.append({
                'timestamp': datetime.now(),
                'price': fill_price,
                'size': fill_size,
                'pnl': pnl,
                'total_pnl': self.total_pnl
            })
            
        except Exception as e:
            logger.error(f"Error handling trade update: {e}")

    def adjust_strategy_parameters(self) -> None:
        """Dynamically adjust strategy parameters based on performance"""
        try:
            recent_trades = [t for t in self.trade_history 
                           if (datetime.now() - t['timestamp']).total_seconds() < 3600]
            
            if len(recent_trades) >= 5:
                # Calculate win rate
                profitable_trades = sum(1 for t in recent_trades 
                                     if t['price'] > t['entry_price'] == t['is_buy'])
                win_rate = profitable_trades / len(recent_trades)
                
                # Adjust momentum threshold
                if win_rate > 0.6:  # Good performance
                    self.momentum_threshold *= 0.95  # More sensitive
                    self.min_spread *= 0.95  # Tighter spreads
                elif win_rate < 0.4:  # Poor performance
                    self.momentum_threshold *= 1.05  # More conservative
                    self.min_spread *= 1.05  # Wider spreads
                
                logger.info(f"Strategy adjusted - Win rate: {win_rate:.1%}, "
                          f"Momentum threshold: {self.momentum_threshold:.4%}, "
                          f"Spread: {self.min_spread:.4%}")
                
        except Exception as e:
            logger.error(f"Error adjusting strategy: {e}")