"""
Main dashboard orchestration module.
"""

import streamlit as st
import time
import os
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from loguru import logger
from hyperliquid.info import Info

from agent_smith.config import TradingConfig
from agent_smith.dashboard.data_fetchers import DashboardDataFetcher
from agent_smith.dashboard.chart_components import ChartManager
from agent_smith.dashboard.ui_components import UIComponentManager
from agent_smith.exceptions import ConfigurationException, MarketDataException


# Load environment variables
load_dotenv()

# Configure logging for dashboard
logger.remove()
logger.add(
    lambda msg: print(msg),
    format="{time} | {level} | {message}",
    level="DEBUG"
)


def check_environment() -> bool:
    """Check if environment variables are loaded correctly."""
    try:
        required_vars = ['HL_ACCOUNT_ADDRESS', 'HL_SECRET_KEY']
        optional_vars = ['HL_ASSET', 'HL_TESTNET', 'HL_MAX_POSITION']
        
        # Check required variables
        missing = []
        for var in required_vars:
            value = os.getenv(var)
            if not value:
                missing.append(var)
            else:
                logger.debug(f"{var} is set")
                
        if missing:
            st.error(f"Missing required environment variables: {', '.join(missing)}")
            st.stop()
            return False
            
        # Log optional variables
        for var in optional_vars:
            value = os.getenv(var)
            if value:
                logger.debug(f"{var} = {value}")
            else:
                logger.debug(f"{var} not set (using default)")
                
        return True
        
    except Exception as e:
        logger.error(f"Error checking environment: {e}")
        st.error(f"Environment check failed: {e}")
        return False


def initialize_config() -> TradingConfig:
    """Initialize trading configuration from environment variables."""
    try:
        # Required settings
        account_address = os.getenv('HL_ACCOUNT_ADDRESS')
        secret_key = os.getenv('HL_SECRET_KEY')
        
        if not account_address or not secret_key:
            raise ConfigurationException("Missing required configuration")
            
        # Optional settings with defaults
        asset = os.getenv('HL_ASSET', 'BTC')
        is_testnet = os.getenv('HL_TESTNET', 'false').lower() == 'true'
        max_position = float(os.getenv('HL_MAX_POSITION', '1.0'))
        
        # Set exchange URL based on testnet flag
        if is_testnet:
            exchange_url = "https://api.hyperliquid-testnet.xyz"
            logger.info("Using testnet configuration")
        else:
            exchange_url = "https://api.hyperliquid.xyz"
            logger.info("Using mainnet configuration")
            
        return TradingConfig(
            account_address=account_address,
            secret_key=secret_key,
            asset=asset,
            exchange_url=exchange_url,
            max_position=max_position
        )
        
    except Exception as e:
        logger.error(f"Configuration initialization failed: {e}")
        raise ConfigurationException(f"Failed to initialize config: {e}")


@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_cached_data(address: str, asset: str, lookback_hours: int) -> Dict[str, Any]:
    """Get cached dashboard data to improve performance."""
    try:
        # This would integrate with the data fetcher
        # For now, return empty dict
        return {}
    except Exception as e:
        logger.error(f"Error getting cached data: {e}")
        return {}


def initialize_dashboard_components(config: TradingConfig) -> tuple:
    """Initialize all dashboard components."""
    try:
        # Initialize Info client
        info = Info(base_url=config.exchange_url)
        
        # Initialize components
        data_fetcher = DashboardDataFetcher(info, config)
        chart_manager = ChartManager()
        ui_manager = UIComponentManager()
        
        return data_fetcher, chart_manager, ui_manager, info
        
    except Exception as e:
        logger.error(f"Failed to initialize dashboard components: {e}")
        raise ConfigurationException(f"Dashboard initialization failed: {e}")


def render_dashboard(
    data_fetcher: DashboardDataFetcher,
    chart_manager: ChartManager,
    ui_manager: UIComponentManager,
    config: TradingConfig,
    settings: Dict[str, Any]
) -> None:
    """Render the main dashboard interface."""
    try:
        # Display header
        ui_manager.display_header()
        
        # Get fresh data
        with st.spinner("Loading market data..."):
            try:
                market_data = data_fetcher.get_market_data()
                user_state = data_fetcher.get_user_state(config.account_address)
                trades_df = data_fetcher.get_trades_history(
                    config.account_address, 
                    settings['time_range']
                )
                pnl_metrics = data_fetcher.calculate_pnl_metrics(trades_df)
                
                # Combine metrics
                combined_metrics = {**user_state, **pnl_metrics}
                
            except MarketDataException as e:
                st.error(f"Failed to load data: {e}")
                return
                
        # Display metrics row
        ui_manager.display_metrics_row(combined_metrics)
        
        # Display market data
        ui_manager.display_market_data(market_data)
        
        # Create tabs for different views
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Performance", "💹 Charts", "📋 Trades", "⚙️ Settings"])
        
        with tab1:
            st.subheader("Performance Overview")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # PnL chart
                pnl_chart = chart_manager.create_pnl_chart(trades_df)
                st.plotly_chart(pnl_chart, use_container_width=True)
                
            with col2:
                # Performance metrics gauge
                metrics_chart = chart_manager.create_performance_metrics_chart(pnl_metrics)
                st.plotly_chart(metrics_chart, use_container_width=True)
                
            # Trade distribution
            dist_chart = chart_manager.create_trade_distribution_chart(trades_df)
            st.plotly_chart(dist_chart, use_container_width=True)
            
        with tab2:
            st.subheader("Market Charts")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Volume chart
                volume_chart = chart_manager.create_volume_chart(trades_df)
                st.plotly_chart(volume_chart, use_container_width=True)
                
            with col2:
                # Price chart (would need price history)
                st.info("Price charts require historical price data feed")
                
        with tab3:
            st.subheader("Trade History")
            ui_manager.display_trades_table(trades_df)
            
        with tab4:
            st.subheader("Dashboard Settings")
            
            st.write("**Current Configuration:**")
            st.json({
                'asset': config.asset,
                'account_address': config.account_address[:10] + "...",
                'exchange_url': config.exchange_url,
                'max_position': config.max_position
            })
            
            st.write("**Data Settings:**")
            st.write(f"Time Range: {settings['time_range']} hours")
            st.write(f"Auto Refresh: {settings['auto_refresh']}")
            if settings['refresh_interval']:
                st.write(f"Refresh Interval: {settings['refresh_interval']} seconds")
                
        # Display status indicators
        status_data = {
            'is_connected': True,  # Would check actual connection
            'data_age_seconds': 30,  # Would calculate from last update
            'error_count': 0  # Would track errors
        }
        ui_manager.display_status_indicators(status_data)
        
    except Exception as e:
        logger.error(f"Error rendering dashboard: {e}")
        st.error(f"Dashboard rendering failed: {e}")


def main() -> None:
    """Main dashboard application entry point."""
    try:
        # Check environment
        if not check_environment():
            st.stop()
            return
            
        # Initialize configuration
        try:
            config = initialize_config()
        except ConfigurationException as e:
            st.error(f"Configuration error: {e}")
            st.stop()
            return
            
        # Initialize dashboard components
        try:
            data_fetcher, chart_manager, ui_manager, info = initialize_dashboard_components(config)
        except ConfigurationException as e:
            st.error(f"Dashboard initialization error: {e}")
            st.stop()
            return
            
        # Create sidebar controls
        sidebar_settings = ui_manager.create_sidebar({
            'asset': config.asset,
            'auto_refresh': True
        })
        
        # Auto-refresh logic
        if sidebar_settings.get('auto_refresh') and sidebar_settings.get('refresh_interval'):
            refresh_interval = sidebar_settings['refresh_interval']
            
            # Display countdown
            placeholder = st.empty()
            
            # Render dashboard
            render_dashboard(data_fetcher, chart_manager, ui_manager, config, sidebar_settings)
            
            # Auto-refresh countdown
            for i in range(refresh_interval, 0, -1):
                placeholder.text(f"Next refresh in {i} seconds...")
                time.sleep(1)
                
            placeholder.empty()
            st.rerun()
            
        else:
            # Render dashboard without auto-refresh
            render_dashboard(data_fetcher, chart_manager, ui_manager, config, sidebar_settings)
            
    except Exception as e:
        logger.error(f"Fatal error in dashboard main: {e}")
        st.error(f"Dashboard failed to start: {e}")
        
    finally:
        # Cleanup if needed
        logger.info("Dashboard session ended")


if __name__ == "__main__":
    main()