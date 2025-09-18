"""
Main AgentSmith trading agent class - refactored for modularity.
"""

from typing import Dict, Optional
from datetime import datetime
import eth_account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from loguru import logger

from agent_smith.config import TradingConfig
from agent_smith.metrics import MetricsTracker
from agent_smith.rate_limit import RateLimitHandler
from agent_smith.core import TradingEngine, MarketDataManager, OrderManager, PositionManager
from agent_smith.exceptions import TradingException, ConfigurationException
from agent_smith.logging_utils import logger, print_status_update


class AgentSmith:
    """
    Main trading agent for perpetual futures on Hyperliquid.
    
    This refactored version uses a modular architecture with separate
    components for market data, order management, position tracking,
    and trade execution.
    """
    
    def __init__(self, config: TradingConfig):
        """Initialize the trading agent with modular components."""
        try:
            logger.info("Initializing AgentSmith trading agent...")
            
            # Store configuration
            self.config = config
            
            # Initialize exchange clients
            self._initialize_clients(config)
            
            # Initialize core components
            self._initialize_components()
            
            # Initialize trading engine
            self.trading_engine = TradingEngine(
                market_data=self.market_data,
                order_manager=self.order_manager,
                position_manager=self.position_manager,
                config=config,
                metrics_tracker=self.metrics_tracker
            )
            
            # Setup initial state
            self._setup_initial_state()
            
            logger.success("AgentSmith initialization complete")
            
        except Exception as e:
            logger.error(f"Failed to initialize AgentSmith: {e}")
            raise ConfigurationException(f"Agent initialization failed: {e}")
            
    def run(self) -> None:
        """Start the trading agent."""
        try:
            logger.info("Starting AgentSmith trading agent...")
            self.trading_engine.run()
            
        except KeyboardInterrupt:
            logger.info("Trading interrupted by user")
            self.stop()
        except Exception as e:
            logger.error(f"Fatal error in agent: {e}")
            raise TradingException(f"Agent execution failed: {e}")
            
    def stop(self) -> None:
        """Stop the trading agent gracefully."""
        try:
            logger.info("Stopping AgentSmith...")
            
            if hasattr(self, 'trading_engine'):
                self.trading_engine.stop()
                
            logger.info("AgentSmith stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping agent: {e}")
            
    def get_current_state(self) -> Dict:
        """Get current trading state and metrics."""
        try:
            if hasattr(self, 'trading_engine'):
                engine_state = self.trading_engine.get_current_state()
                
                # Add additional agent-level information
                engine_state.update({
                    'agent_version': '2.0',
                    'config': {
                        'asset': self.config.asset,
                        'max_position': self.config.max_position,
                        'exchange_url': self.config.exchange_url
                    },
                    'initialization_time': getattr(self, '_init_time', None)
                })
                
                return engine_state
            else:
                return {'status': 'not_initialized'}
                
        except Exception as e:
            logger.error(f"Error getting current state: {e}")
            return {'status': 'error', 'error': str(e)}
            
    def get_position(self) -> float:
        """Get current position size."""
        try:
            market_state = self.market_data.get_perp_market_state()
            return market_state.position if market_state else 0.0
            
        except Exception as e:
            logger.error(f"Error getting position: {e}")
            return 0.0
            
    def get_market_state(self) -> Optional[Dict]:
        """Get current market state."""
        try:
            market_state = self.market_data.get_perp_market_state()
            if not market_state:
                return None
                
            return {
                'asset': market_state.asset,
                'mark_price': market_state.mark_price,
                'best_bid': market_state.best_bid,
                'best_ask': market_state.best_ask,
                'position': market_state.position,
                'spread': market_state.best_ask - market_state.best_bid,
                'spread_pct': (market_state.best_ask - market_state.best_bid) / market_state.mark_price
            }
            
        except Exception as e:
            logger.error(f"Error getting market state: {e}")
            return None
            
    def cancel_all_orders(self) -> None:
        """Cancel all open orders."""
        try:
            self.order_manager.cancel_all_orders()
            
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")
            raise TradingException(f"Failed to cancel orders: {e}")
            
    def get_performance_metrics(self) -> Dict:
        """Get trading performance metrics."""
        try:
            if self.metrics_tracker:
                return self.metrics_tracker.get_summary()
            else:
                return {}
                
        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            return {}
            
    def _initialize_clients(self, config: TradingConfig) -> None:
        """Initialize Hyperliquid exchange clients."""
        try:
            # Initialize Info client
            self.info = Info(base_url=config.exchange_url)
            logger.info("Info client initialized")
            
            # Initialize Exchange client
            wallet = eth_account.Account.from_key(config.secret_key)
            self.exchange = Exchange(
                wallet=wallet,
                base_url=config.exchange_url,
                account_address=config.account_address
            )
            logger.info("Exchange client initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize clients: {e}")
            raise ConfigurationException(f"Client initialization failed: {e}")
            
    def _initialize_components(self) -> None:
        """Initialize core trading components."""
        try:
            # Initialize rate limiting
            self.rate_limit_handler = RateLimitHandler()
            
            # Initialize market data manager
            self.market_data = MarketDataManager(self.info, self.config)
            
            # Initialize position manager
            self.position_manager = PositionManager(self.config)
            
            # Initialize order manager
            self.order_manager = OrderManager(
                self.exchange, 
                self.info, 
                self.config, 
                self.rate_limit_handler
            )
            
            # Initialize metrics tracker (optional)
            try:
                self.metrics_tracker = MetricsTracker(self.info, self.config.account_address)
            except Exception as e:
                logger.warning(f"Could not initialize metrics tracker: {e}")
                self.metrics_tracker = None
                
            logger.info("Core components initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize components: {e}")
            raise ConfigurationException(f"Component initialization failed: {e}")
            
    def _setup_initial_state(self) -> None:
        """Setup initial trading state and display status."""
        try:
            # Get accurate position state
            position_state = self.market_data.get_accurate_position_state(
                self.config.account_address
            )
            
            # Update position manager with initial state
            if position_state.get('position', 0) != 0:
                market_state = self.market_data.get_perp_market_state()
                if market_state:
                    self.position_manager.update_position_state(
                        market_state,
                        position_state.get('entry_price')
                    )
                    
            # Display initial status
            self._display_initial_status(position_state)
            
            # Store initialization time
            self._init_time = datetime.now().isoformat()
            
        except Exception as e:
            logger.error(f"Error setting up initial state: {e}")
            raise ConfigurationException(f"Initial state setup failed: {e}")
            
    def _display_initial_status(self, position_state: Dict) -> None:
        """Display initial status information."""
        try:
            # Prepare status information
            status_info = {
                'position': position_state.get('position', 0),
                'entry_price': position_state.get('entry_price', 0),
                'account_value': 0,  # This would need to be calculated
                'current_price': 0,  # This would need to be fetched
                'pnl': 0,  # This would need to be calculated
                'asset': self.config.asset,
                'volume': 0  # 24h volume - would need to be fetched
            }
            
            # Get current market price
            market_state = self.market_data.get_perp_market_state()
            if market_state:
                status_info['current_price'] = market_state.mark_price
                
                # Calculate PnL if we have a position
                if (status_info['position'] != 0 and 
                    status_info['entry_price'] != 0 and 
                    status_info['current_price'] != 0):
                    
                    pnl = ((status_info['current_price'] - status_info['entry_price']) * 
                           status_info['position'])
                    status_info['pnl'] = pnl
                    
            # Display status update
            print_status_update(status_info)
            
        except Exception as e:
            logger.error(f"Error displaying initial status: {e}")


