"""
Main trading engine that orchestrates all trading components.
"""

import time
from typing import List, Optional
from datetime import datetime, timedelta
from loguru import logger

from .market_data import MarketDataManager
from .order_manager import OrderManager
from .position_manager import PositionManager
from ..strategies.enhanced_market_maker import EnhancedPerpMarketMaker
from ..strategies.position_reducer import PositionReducer
from ..trading_types import PerpMarketState, Order
from ..config import TradingConfig
from ..metrics import MetricsTracker
from ..exceptions import TradingException, MarketDataException


class TradingEngine:
    """Main trading engine that coordinates all components."""
    
    def __init__(
        self,
        market_data: MarketDataManager,
        order_manager: OrderManager,
        position_manager: PositionManager,
        config: TradingConfig,
        metrics_tracker: Optional[MetricsTracker] = None
    ):
        self.market_data = market_data
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.config = config
        self.metrics_tracker = metrics_tracker
        
        # Initialize strategy and position reducer
        self.strategy = EnhancedPerpMarketMaker(config)
        self.position_reducer = PositionReducer(order_manager.exchange)
        
        # Trading state
        self.is_running = False
        self.last_trade_time = datetime.now()
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        
    def run(self) -> None:
        """Start the main trading loop."""
        try:
            self.is_running = True
            logger.info("Starting trading engine...")
            
            # Setup initial state
            self._setup_initial_state()
            
            # Main trading loop
            self.trading_loop()
            
        except KeyboardInterrupt:
            logger.info("Trading interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error in trading engine: {e}")
            raise TradingException(f"Trading engine failed: {e}")
        finally:
            self.is_running = False
            logger.info("Trading engine stopped")
            
    def trading_loop(self) -> None:
        """Main trading loop with error handling and recovery."""
        while self.is_running:
            try:
                # Get current market state
                market_state = self.market_data.get_perp_market_state()
                if not market_state:
                    logger.warning("Failed to get market state - retrying in 30s")
                    time.sleep(30)
                    continue
                    
                # Validate market data quality
                if not self.market_data.validate_market_data(market_state):
                    logger.warning("Invalid market data - skipping cycle")
                    time.sleep(10)
                    continue
                    
                # Update position tracking
                self.position_manager.update_position_state(market_state)
                
                # Check and handle position management
                position_handled = self._handle_position_management(market_state)
                
                if not position_handled:
                    # Generate and execute trading orders
                    self._execute_trading_cycle(market_state)
                    
                # Update metrics if available
                if self.metrics_tracker:
                    self._update_metrics(market_state)
                    
                # Reset error counter on successful cycle
                self.consecutive_errors = 0
                
                # Sleep between cycles
                time.sleep(10)
                
            except MarketDataException as e:
                logger.error(f"Market data error: {e}")
                self._handle_error("market_data")
                
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                self._handle_error("general")
                
    def stop(self) -> None:
        """Stop the trading engine gracefully."""
        logger.info("Stopping trading engine...")
        self.is_running = False
        
        try:
            # Cancel all open orders
            self.order_manager.cancel_all_orders()
            logger.info("Cancelled all open orders")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            
    def get_current_state(self) -> dict:
        """Get current trading engine state."""
        try:
            market_state = self.market_data.get_perp_market_state()
            if not market_state:
                return {'status': 'no_market_data'}
                
            position_metrics = self.position_manager.get_position_metrics(market_state)
            strategy_metrics = self.strategy.get_strategy_metrics()
            
            return {
                'status': 'running' if self.is_running else 'stopped',
                'market_state': {
                    'asset': market_state.asset,
                    'mark_price': market_state.mark_price,
                    'best_bid': market_state.best_bid,
                    'best_ask': market_state.best_ask,
                    'position': market_state.position
                },
                'position_metrics': position_metrics,
                'strategy_metrics': strategy_metrics,
                'consecutive_errors': self.consecutive_errors,
                'last_trade_time': self.last_trade_time.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting current state: {e}")
            return {'status': 'error', 'error': str(e)}
            
    def _setup_initial_state(self) -> None:
        """Setup initial trading state."""
        try:
            logger.info("Setting up initial trading state...")
            
            # Get accurate position state
            position_state = self.market_data.get_accurate_position_state(self.config.account_address)
            
            # Update position manager
            if position_state.get('position', 0) != 0:
                market_state = self.market_data.get_perp_market_state()
                if market_state:
                    self.position_manager.update_position_state(
                        market_state, 
                        position_state.get('entry_price')
                    )
                    
            logger.info("Initial state setup complete")
            
        except Exception as e:
            logger.error(f"Error setting up initial state: {e}")
            raise TradingException(f"Failed to setup initial state: {e}")
            
    def _handle_position_management(self, market_state: PerpMarketState) -> bool:
        """Handle position management tasks. Returns True if position action was taken."""
        try:
            # Check position status
            self.position_manager.check_position_status(market_state)
            
            # Check if position needs reduction
            if self.position_manager.should_reduce_position(market_state.position):
                logger.info("Position size requires reduction")
                
                success = self.strategy.execute_position_reduction(market_state)
                if success:
                    logger.success("Position reduction executed successfully")
                    return True
                else:
                    logger.warning("Position reduction failed")
                    
            return False
            
        except Exception as e:
            logger.error(f"Error handling position management: {e}")
            return False
            
    def _execute_trading_cycle(self, market_state: PerpMarketState) -> None:
        """Execute a single trading cycle."""
        try:
            # Check if we should trade
            if not self.strategy.should_trade(market_state):
                logger.debug("Strategy conditions not met for trading")
                return
                
            # Generate orders from strategy
            orders = self.strategy.calculate_orders(market_state)
            
            if not orders:
                logger.debug("No orders generated by strategy")
                return
                
            logger.info(f"Generated {len(orders)} orders")
            
            # Execute orders
            self.order_manager.execute_perp_orders(orders)
            
            # Update last trade time
            self.last_trade_time = datetime.now()
            
        except Exception as e:
            logger.error(f"Error in trading cycle: {e}")
            raise
            
    def _update_metrics(self, market_state: PerpMarketState) -> None:
        """Update performance metrics."""
        try:
            if not self.metrics_tracker:
                return

            # Update metrics using the existing method
            self.metrics_tracker.update_metrics()
            
        except Exception as e:
            logger.error(f"Error updating metrics: {e}")
            
    def _handle_error(self, error_type: str) -> None:
        """Handle errors with appropriate backoff and recovery."""
        self.consecutive_errors += 1
        
        if self.consecutive_errors >= self.max_consecutive_errors:
            logger.error(f"Too many consecutive errors ({self.consecutive_errors}). Stopping trading.")
            self.stop()
            return
            
        # Progressive backoff
        sleep_time = min(60, 5 * self.consecutive_errors)
        logger.warning(f"Error #{self.consecutive_errors}, sleeping for {sleep_time}s")
        time.sleep(sleep_time)