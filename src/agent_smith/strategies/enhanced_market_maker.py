"""
Enhanced market maker strategy for perpetual futures trading.
"""

from typing import List, Optional, Tuple
from datetime import datetime, timedelta
from loguru import logger

from agent_smith.strategies.base import PerpStrategy
from agent_smith.strategies.risk_manager import DynamicRiskManager
from agent_smith.strategies.momentum_analyzer import MomentumAnalyzer
from agent_smith.strategies.order_utils import (
    calculate_optimal_size,
    validate_order_parameters,
    calculate_spread_metrics,
    adjust_size_for_decimals,
    get_size_decimals
)
from agent_smith.trading_types import PerpMarketState, Order, OrderSide
from agent_smith.config import TradingConfig
from agent_smith.exceptions import (
    OrderExecutionException,
    RiskManagementException,
    MarketDataException
)


class EnhancedPerpMarketMaker(PerpStrategy):
    """Enhanced perpetual futures market maker with momentum and risk management."""
    
    def __init__(
        self,
        config: TradingConfig,
        min_spread: float = 0.002,
        base_position: float = 0.25,
        max_position: float = 5.0,
        min_order_interval: int = 60,
        min_notional: float = 12.0,
        min_size: float = 0.01
    ):
        super().__init__(config)
        self.min_spread = min_spread
        self.base_position = base_position
        self.max_position = max_position
        self.min_order_interval = min_order_interval
        self.min_notional = min_notional
        self.min_size = min_size
        
        # Initialize components
        self.risk_manager = DynamicRiskManager(config, max_position)
        self.momentum_analyzer = MomentumAnalyzer()
        
        # Trading state
        self.last_order_time = datetime.now() - timedelta(minutes=5)
        self.position_entry_price: Optional[float] = None
        self.current_position = 0.0
        
    def calculate_orders(self, market_state: PerpMarketState) -> List[Order]:
        """Calculate orders with momentum-based strategy."""
        try:
            orders = []
            
            # Check if we should trade
            if not self._should_trade(market_state):
                return orders
                
            # Calculate base order size
            base_size = self._calculate_base_size(market_state)
            
            # Check for momentum signals
            momentum_signal = self.momentum_analyzer.calculate_market_momentum(
                market_state.mark_price,
                market_state.best_bid,
                market_state.best_ask
            )
            
            if momentum_signal and self.momentum_analyzer.should_trade_momentum():
                # Create momentum-based order
                momentum_order = self._create_momentum_order(
                    market_state, momentum_signal, base_size
                )
                if momentum_order:
                    orders.append(momentum_order)
                    self.momentum_analyzer.update_momentum_trade()
            else:
                # Create regular market making orders
                mm_orders = self._create_market_making_orders(market_state, base_size)
                orders.extend(mm_orders)
            
            return orders
                
        except Exception as e:
            logger.error(f"Error calculating orders: {e}")
            raise OrderExecutionException(f"Order calculation failed: {e}")
            
    def should_trade(self, market_state: PerpMarketState) -> bool:
        """Enhanced trade entry conditions."""
        try:
            return self._should_trade(market_state)
        except Exception as e:
            logger.error(f"Error in should_trade: {e}")
            return False
            
    def execute_position_reduction(self, market_state: PerpMarketState) -> bool:
        """Execute position reduction with proper error handling."""
        try:
            if market_state.position == 0:
                return True
                
            reduction_size = min(0.57, abs(market_state.position))
            is_long = market_state.position > 0
            
            # Calculate aggressive price with slippage
            price_impact = 0.005  # 0.5% price impact
            reduce_price = market_state.mark_price * (
                (1 - price_impact) if is_long else (1 + price_impact)
            )
            
            # Try IOC order first
            result = self._execute_ioc_reduction(
                market_state.asset, reduction_size, reduce_price, is_long
            )
            
            if result:
                return True
                
            # Fallback to market order
            return self._execute_market_reduction(market_state.asset, reduction_size)
            
        except Exception as e:
            logger.error(f"Error reducing position: {e}")
            raise OrderExecutionException(f"Position reduction failed: {e}")
            
    def on_trade_update(self, fill_price: float, fill_size: float, pnl: float) -> None:
        """Handle trade updates and adjust strategy."""
        try:
            self.risk_manager.update_trade_history(fill_price, fill_size, pnl)
            
            if pnl > 0:
                logger.info("Profitable trade recorded")
            else:
                logger.warning(f"Loss recorded: ${pnl:.2f}")
                
        except Exception as e:
            logger.error(f"Error handling trade update: {e}")
            
    def get_strategy_metrics(self) -> dict:
        """Get current strategy performance metrics."""
        try:
            risk_metrics = self.risk_manager.get_risk_metrics()
            vol_metrics = self.momentum_analyzer.get_volatility_metrics()
            
            return {
                **risk_metrics,
                **vol_metrics,
                'strategy_type': 'enhanced_market_maker',
                'min_spread': self.min_spread,
                'max_position': self.max_position
            }
            
        except Exception as e:
            logger.error(f"Error getting strategy metrics: {e}")
            return {}
            
    def _should_trade(self, market_state: PerpMarketState) -> bool:
        """Check if trading conditions are met."""
        # Check spread
        spread_metrics = calculate_spread_metrics(market_state)
        threshold = self._calculate_spread_threshold(market_state)
        
        if spread_metrics.get('spread_pct', 0) < threshold:
            return False
            
        # Check volatility
        vol_metrics = self.momentum_analyzer.get_volatility_metrics()
        if vol_metrics.get('is_high_vol', False):
            logger.info("High volatility - waiting for calmer market")
            return False
            
        # Check recent performance
        risk_metrics = self.risk_manager.get_risk_metrics()
        if risk_metrics.get('win_rate', 1.0) < 0.3:  # Less than 30% win rate
            logger.warning("Poor recent performance - reducing trading")
            return False
            
        return True
        
    def _calculate_base_size(self, market_state: PerpMarketState) -> float:
        """Calculate base order size."""
        try:
            optimal_size = calculate_optimal_size(
                market_state.mark_price, 
                self.min_notional
            )
            
            # Adjust for asset decimals
            size = adjust_size_for_decimals(optimal_size, market_state.asset)
            
            return max(size, self.min_size)
            
        except Exception as e:
            logger.error(f"Error calculating base size: {e}")
            return self.min_size
            
    def _create_momentum_order(
        self, 
        market_state: PerpMarketState, 
        signal: str, 
        base_size: float
    ) -> Optional[Order]:
        """Create momentum-based order."""
        try:
            # Increase size for momentum trades
            momentum_size = base_size * 1.5
            side = OrderSide.BUY if signal == "long" else OrderSide.SELL
            
            # Check position limits
            if not self.risk_manager.check_position_limits(
                market_state, momentum_size, side == OrderSide.BUY
            ):
                return None
                
            order = Order(
                size=momentum_size,
                price=market_state.mark_price,
                side=side,
                reduce_only=False,
                post_only=False  # Market order
            )
            
            if validate_order_parameters(order, market_state):
                logger.info(f"Generated momentum {side.value} order: {momentum_size:.4f}")
                return order
                
            return None
            
        except Exception as e:
            logger.error(f"Error creating momentum order: {e}")
            return None
            
    def _create_market_making_orders(
        self, 
        market_state: PerpMarketState, 
        base_size: float
    ) -> List[Order]:
        """Create regular market making orders."""
        orders = []
        
        try:
            # Create buy order if within limits
            if self.risk_manager.check_position_limits(
                market_state, base_size, True
            ):
                buy_order = Order(
                    size=base_size,
                    price=market_state.mark_price,
                    side=OrderSide.BUY,
                    reduce_only=False,
                    post_only=False
                )
                if validate_order_parameters(buy_order, market_state):
                    orders.append(buy_order)
                    
            # Create sell order if within limits
            if self.risk_manager.check_position_limits(
                market_state, base_size, False
            ):
                sell_order = Order(
                    size=base_size,
                    price=market_state.mark_price,
                    side=OrderSide.SELL,
                    reduce_only=False,
                    post_only=False
                )
                if validate_order_parameters(sell_order, market_state):
                    orders.append(sell_order)
                    
        except Exception as e:
            logger.error(f"Error creating market making orders: {e}")
            
        return orders
        
    def _calculate_spread_threshold(self, market_state: PerpMarketState) -> float:
        """Calculate dynamic spread threshold."""
        base_threshold = 0.0004  # 4 bps
        
        position_usage = abs(market_state.position) / self.max_position
        
        if position_usage > 0.8:
            return 0.0002  # 2 bps when position is high
        elif position_usage < 0.3:
            return 0.0003  # 3 bps when position is low
            
        return base_threshold
        
    def _execute_ioc_reduction(
        self, 
        asset: str, 
        size: float, 
        price: float, 
        is_long: bool
    ) -> bool:
        """Execute IOC order for position reduction."""
        try:
            result = self.exchange.order(
                name=asset,
                is_buy=not is_long,
                sz=size,
                limit_px=price,
                order_type={"limit": {"tif": "Ioc"}},
                reduce_only=True,
                builder={
                    "b": "0x8c967E73E7B15087c42A10D344cFf4c96D877f1D",
                    "f": 1
                }
            )
            
            if result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    fill = statuses[0]["filled"]
                    logger.success(
                        f"Position reduced: {float(fill['totalSz']):.4f} @ "
                        f"${float(fill['avgPx']):.4f}"
                    )
                    return True
                    
            return False
            
        except Exception as e:
            logger.error(f"Error executing IOC reduction: {e}")
            return False
            
    def _execute_market_reduction(self, asset: str, size: float) -> bool:
        """Execute market order for position reduction."""
        try:
            result = self.exchange.market_close(
                coin=asset,
                sz=size,
                slippage=0.01
            )
            
            if result.get("status") == "ok":
                statuses = result.get("response", {}).get("data", {}).get("statuses", [])
                if statuses and "filled" in statuses[0]:
                    fill = statuses[0]["filled"]
                    logger.success(
                        f"Position reduced via market: {float(fill['totalSz']):.4f} @ "
                        f"${float(fill['avgPx']):.4f}"
                    )
                    return True
                    
            return False
            
        except Exception as e:
            logger.error(f"Error executing market reduction: {e}")
            return False