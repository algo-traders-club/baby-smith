"""
UI components and styling for the dashboard.
"""

import streamlit as st
import pandas as pd
from typing import Dict, Any, Optional, List
import os
from loguru import logger

from agent_smith.exceptions import ValidationException


class UIComponentManager:
    """Manages UI components and styling for the dashboard."""
    
    def __init__(self):
        self.setup_page_config()
        
    def setup_page_config(self) -> None:
        """Configure Streamlit page settings."""
        try:
            st.set_page_config(
                page_title="Baby Smith Trading Dashboard",
                page_icon="🤖",
                layout="wide",
                initial_sidebar_state="expanded"
            )
            
            # Load custom CSS
            self._load_custom_css()
            
        except Exception as e:
            logger.error(f"Error setting up page config: {e}")
            
    def display_header(self, title: str = "Baby Smith Trading Dashboard") -> None:
        """Display the main dashboard header."""
        try:
            col1, col2, col3 = st.columns([1, 2, 1])
            
            with col1:
                logo_path = self._get_logo_path()
                if logo_path and os.path.exists(logo_path):
                    st.image(logo_path, width=100)
                    
            with col2:
                st.title(title)
                
            with col3:
                st.write("")  # Empty column for spacing
                
            st.divider()
            
        except Exception as e:
            logger.error(f"Error displaying header: {e}")
            st.title(title)  # Fallback
            
    def display_metrics_row(self, metrics: Dict[str, Any]) -> None:
        """Display key metrics in a row of columns."""
        try:
            if not metrics:
                st.warning("No metrics available")
                return
                
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                account_value = metrics.get('account_value', 0)
                st.metric(
                    "Account Value",
                    f"${account_value:,.2f}",
                    delta=None
                )
                
            with col2:
                position = metrics.get('current_position', 0)
                position_color = "normal"
                if position > 0:
                    position_color = "normal"
                elif position < 0:
                    position_color = "inverse"
                    
                st.metric(
                    "Position",
                    f"{position:.4f}",
                    delta=None
                )
                
            with col3:
                unrealized_pnl = metrics.get('unrealized_pnl', 0)
                pnl_delta = f"${unrealized_pnl:+.2f}" if unrealized_pnl != 0 else None
                
                st.metric(
                    "Unrealized PnL",
                    f"${unrealized_pnl:.2f}",
                    delta=pnl_delta
                )
                
            with col4:
                total_pnl = metrics.get('total_pnl', 0)
                pnl_delta = f"${total_pnl:+.2f}" if total_pnl != 0 else None
                
                st.metric(
                    "Total PnL",
                    f"${total_pnl:.2f}",
                    delta=pnl_delta
                )
                
            with col5:
                win_rate = metrics.get('win_rate', 0)
                win_rate_pct = win_rate * 100
                
                st.metric(
                    "Win Rate",
                    f"{win_rate_pct:.1f}%",
                    delta=None
                )
                
        except Exception as e:
            logger.error(f"Error displaying metrics row: {e}")
            st.error("Error displaying metrics")
            
    def display_market_data(self, market_data: Dict[str, Any]) -> None:
        """Display current market data."""
        try:
            if not market_data:
                st.warning("No market data available")
                return
                
            st.subheader("Market Data")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                bid = market_data.get('best_bid', 0)
                st.metric("Best Bid", f"${bid:.4f}")
                
            with col2:
                ask = market_data.get('best_ask', 0)
                st.metric("Best Ask", f"${ask:.4f}")
                
            with col3:
                spread = market_data.get('spread', 0)
                st.metric("Spread", f"${spread:.4f}")
                
            with col4:
                spread_bps = market_data.get('spread_bps', 0)
                st.metric("Spread (bps)", f"{spread_bps:.2f}")
                
        except Exception as e:
            logger.error(f"Error displaying market data: {e}")
            st.error("Error displaying market data")
            
    def display_trades_table(self, trades_df: pd.DataFrame) -> None:
        """Display recent trades table."""
        try:
            if trades_df.empty:
                st.info("No recent trades found")
                return
                
            st.subheader("Recent Trades")
            
            # Format the DataFrame for display
            display_df = trades_df.copy()
            
            # Select and format columns
            columns_to_show = ['time', 'coin', 'side', 'sz', 'px', 'fee', 'closedPnl']
            available_columns = [col for col in columns_to_show if col in display_df.columns]
            
            if available_columns:
                display_df = display_df[available_columns]
                
                # Format numeric columns
                if 'sz' in display_df.columns:
                    display_df['sz'] = display_df['sz'].apply(lambda x: f"{x:.4f}")
                if 'px' in display_df.columns:
                    display_df['px'] = display_df['px'].apply(lambda x: f"${x:.4f}")
                if 'fee' in display_df.columns:
                    display_df['fee'] = display_df['fee'].apply(lambda x: f"${x:.4f}")
                if 'closedPnl' in display_df.columns:
                    display_df['closedPnl'] = display_df['closedPnl'].apply(
                        lambda x: f"${x:+.2f}" if pd.notnull(x) else "N/A"
                    )
                    
                # Format time column
                if 'time' in display_df.columns:
                    display_df['time'] = display_df['time'].dt.strftime('%H:%M:%S')
                    
                # Rename columns for display
                column_names = {
                    'time': 'Time',
                    'coin': 'Asset',
                    'side': 'Side',
                    'sz': 'Size',
                    'px': 'Price',
                    'fee': 'Fee',
                    'closedPnl': 'PnL'
                }
                
                display_df = display_df.rename(columns=column_names)
                
                # Display with styling
                st.dataframe(
                    display_df,
                    use_container_width=True,
                    height=300
                )
            else:
                st.warning("No displayable columns found in trades data")
                
        except Exception as e:
            logger.error(f"Error displaying trades table: {e}")
            st.error("Error displaying trades table")
            
    def create_sidebar(self, config_options: Dict[str, Any]) -> Dict[str, Any]:
        """Create and manage the sidebar controls."""
        try:
            st.sidebar.header("Settings")
            
            # Time range selector
            time_range = st.sidebar.selectbox(
                "Data Time Range",
                options=[1, 6, 12, 24, 48],
                index=3,  # Default to 24 hours
                format_func=lambda x: f"{x} hours"
            )
            
            # Asset selector (if multiple assets supported)
            asset = st.sidebar.text_input(
                "Asset",
                value=config_options.get('asset', 'BTC'),
                placeholder="e.g., BTC, ETH"
            )
            
            # Auto-refresh option
            auto_refresh = st.sidebar.checkbox(
                "Auto Refresh",
                value=config_options.get('auto_refresh', True)
            )
            
            # Refresh interval
            if auto_refresh:
                refresh_interval = st.sidebar.selectbox(
                    "Refresh Interval",
                    options=[10, 30, 60, 120],
                    index=1,  # Default to 30 seconds
                    format_func=lambda x: f"{x} seconds"
                )
            else:
                refresh_interval = None
                
            # Manual refresh button
            if st.sidebar.button("🔄 Refresh Data"):
                st.rerun()
                
            # Export options
            st.sidebar.subheader("Export")
            
            if st.sidebar.button("📊 Export Trades"):
                st.sidebar.info("Export functionality coming soon")
                
            return {
                'time_range': time_range,
                'asset': asset,
                'auto_refresh': auto_refresh,
                'refresh_interval': refresh_interval
            }
            
        except Exception as e:
            logger.error(f"Error creating sidebar: {e}")
            return config_options
            
    def display_status_indicators(self, status_data: Dict[str, Any]) -> None:
        """Display system status indicators."""
        try:
            st.subheader("System Status")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                # Connection status
                is_connected = status_data.get('is_connected', False)
                status_color = "🟢" if is_connected else "🔴"
                st.write(f"{status_color} Exchange Connection")
                
            with col2:
                # Data freshness
                data_age = status_data.get('data_age_seconds', 0)
                freshness_color = "🟢" if data_age < 60 else ("🟡" if data_age < 300 else "🔴")
                st.write(f"{freshness_color} Data Age: {data_age:.0f}s")
                
            with col3:
                # Error count
                error_count = status_data.get('error_count', 0)
                error_color = "🟢" if error_count == 0 else ("🟡" if error_count < 5 else "🔴")
                st.write(f"{error_color} Errors: {error_count}")
                
        except Exception as e:
            logger.error(f"Error displaying status indicators: {e}")
            
    def display_error_message(self, error: str, error_type: str = "error") -> None:
        """Display formatted error messages."""
        try:
            if error_type == "warning":
                st.warning(f"⚠️ {error}")
            elif error_type == "info":
                st.info(f"ℹ️ {error}")
            else:
                st.error(f"❌ {error}")
                
        except Exception as e:
            logger.error(f"Error displaying error message: {e}")
            
    def _load_custom_css(self) -> None:
        """Load custom CSS styling."""
        try:
            css = """
            <style>
            .main > div {
                padding-top: 2rem;
            }
            
            .metric-container {
                background-color: #f0f2f6;
                padding: 1rem;
                border-radius: 0.5rem;
                margin-bottom: 1rem;
            }
            
            .positive {
                color: #28a745;
            }
            
            .negative {
                color: #dc3545;
            }
            
            .stTabs [data-baseweb="tab-list"] {
                gap: 2rem;
            }
            </style>
            """
            st.markdown(css, unsafe_allow_html=True)
            
        except Exception as e:
            logger.error(f"Error loading custom CSS: {e}")
            
    def _get_logo_path(self) -> Optional[str]:
        """Get the path to the logo file."""
        try:
            # Look for logo in common locations
            possible_paths = [
                "assets/baby_smith_logo.png",
                "src/assets/baby_smith_logo.png",
                "../assets/baby_smith_logo.png",
                "baby_smith_logo.png"
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    return path
                    
            return None
            
        except Exception as e:
            logger.error(f"Error getting logo path: {e}")
            return None