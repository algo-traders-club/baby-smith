import time
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
import pathlib
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from hyperliquid.info import Info
from hyperliquid.utils import constants  # Add this import
from loguru import logger
import numpy as np
from functools import wraps
from dotenv import load_dotenv
from agent_smith.config import TradingConfig
from agent_smith.metrics import MetricsTracker

# Load environment variables
load_dotenv()

# Configure logging
logger.remove()
logger.add(
    lambda msg: print(msg),
    format="{time} | {level} | {message}",
    level="DEBUG"
)

def check_environment():
    """Check if environment variables are loaded correctly"""
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
        
    # Log optional variables
    for var in optional_vars:
        value = os.getenv(var)
        if value:
            logger.debug(f"{var} = {value}")
        else:
            logger.debug(f"{var} not set, will use default")
            
    return True

# Add this at the start of your main function:
if not check_environment():
    st.stop()

def initialize_config() -> TradingConfig:
    """Initialize configuration with proper environment setup"""
    try:
        # Debug logging
        logger.debug("Starting configuration initialization")
        
        # Load environment variables
        load_dotenv(verbose=True)
        
        # Required environment variables
        required_vars = ['HL_ACCOUNT_ADDRESS', 'HL_SECRET_KEY']
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            st.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            st.stop()
        
        # Force mainnet by default unless explicitly set to testnet
        is_testnet = os.getenv("HL_TESTNET", "false").lower() == "true"
        exchange_url = constants.TESTNET_API_URL if is_testnet else constants.MAINNET_API_URL
        
        # Create config from environment with type checking
        config_params = {
            'account_address': str(os.getenv("HL_ACCOUNT_ADDRESS")),
            'secret_key': str(os.getenv("HL_SECRET_KEY")),
            'asset': str(os.getenv("HL_ASSET", "HYPE")),
            'max_position': float(os.getenv("HL_MAX_POSITION", "5.0")),
            'base_position': float(os.getenv("HL_BASE_POSITION", "1.0")),
            'min_spread': float(os.getenv("HL_MIN_SPREAD", "0.002")),
            'min_order_interval': int(os.getenv("HL_MIN_ORDER_INTERVAL", "30")),
            'profit_take_threshold': float(os.getenv("HL_PROFIT_TAKE_THRESHOLD", "0.01")),
            'stop_loss_threshold': float(os.getenv("HL_STOP_LOSS_THRESHOLD", "0.02")),
            'volatility_window': int(os.getenv("HL_VOLATILITY_WINDOW", "100")),
            'max_open_orders': int(os.getenv("HL_MAX_OPEN_ORDERS", "4")),
            'leverage': int(os.getenv("HL_LEVERAGE", "3")),
            'exchange_url': exchange_url,
            'is_testnet': is_testnet
        }
        
        logger.info(f"Initializing on {'testnet' if is_testnet else 'mainnet'}")
        logger.debug("Configuration parameters loaded successfully")
        
        return TradingConfig(**config_params)
        
    except ValueError as ve:
        logger.error(f"Value error in configuration: {ve}")
        st.error(f"Configuration error: Invalid value in environment variables - {ve}")
        st.stop()
    except Exception as e:
        logger.error(f"Error initializing configuration: {e}")
        st.error(f"Configuration error: {str(e)}")
        st.stop()

# Add DEFAULT_MARKET_DATA constant if not already defined
DEFAULT_MARKET_DATA = {
    'price': 0.0,
    'volume_24h': 0.0,
    'funding_rate': 0.0,
    'open_interest': 0.0
}

# Cache for storing historical data between refreshes
if 'trade_history' not in st.session_state:
    st.session_state.trade_history = pd.DataFrame()
if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = None
if 'config' not in st.session_state:
    st.session_state.config = initialize_config()

def get_logo_path() -> Optional[str]:
    """Get absolute path to logo file if it exists"""
    # Try multiple potential locations
    possible_paths = [
        # Current directory
        pathlib.Path("logo.png"),
        # Relative to script location
        pathlib.Path(__file__).parent / "assets" / "logo.png",
        # Up one level in assets
        pathlib.Path(__file__).parent.parent / "assets" / "logo.png",
    ]
    
    for path in possible_paths:
        if path.exists():
            return str(path)
    return None

# Rate limiting decorator
def rate_limit(seconds: int):
    def decorator(func):
        last_called = {}
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_time = time.time()
            if func.__name__ not in last_called or \
               current_time - last_called[func.__name__] >= seconds:
                last_called[func.__name__] = current_time
                return func(*args, **kwargs)
            else:
                sleep_time = seconds - (current_time - last_called[func.__name__])
                time.sleep(sleep_time)
                last_called[func.__name__] = time.time()
                return func(*args, **kwargs)
        return wrapper
    return decorator

@rate_limit(1)
def get_market_data(info: Info, config: TradingConfig):
    """Get market data with rate limiting and fallbacks"""
    try:
        current_price = 0.0
        # Get current prices with retry
        for attempt in range(3):
            try:
                market_data = info.all_mids()
                if market_data and config.asset in market_data:
                    current_price = float(market_data[config.asset])
                    break
            except Exception as e:
                logger.warning(f"Price fetch attempt {attempt + 1} failed: {str(e)}")
                if attempt == 2:
                    return DEFAULT_MARKET_DATA
                time.sleep(2 ** attempt)
        
        if current_price == 0:
            logger.warning("Could not get current price")
            return DEFAULT_MARKET_DATA
            
        # Get meta data with retry
        meta = None
        for attempt in range(3):
            try:
                meta = info.meta_and_asset_ctxs()
                if meta and len(meta) > 1:
                    break
            except Exception as e:
                logger.warning(f"Metadata fetch attempt {attempt + 1} failed: {str(e)}")
                if attempt == 2:
                    return {
                        'price': current_price,
                        **DEFAULT_MARKET_DATA
                    }
                time.sleep(2 ** attempt)
                
        # Extract asset data with fallbacks
        asset_data = {}
        if meta and len(meta) > 1:
            for item in meta[1]:
                if isinstance(item, dict) and item.get('coin') == config.asset:
                    asset_data = item
                    break
                    
        return {
            'price': current_price,
            'volume_24h': float(asset_data.get('dayNtlVlm', 0)),
            'funding_rate': float(asset_data.get('funding', 0)),
            'open_interest': float(asset_data.get('openInterest', 0))
        }
    except Exception as e:
        logger.error(f"Error getting market data: {e}")
        return None

@rate_limit(1)
def get_user_state(info: Info, address: str):
    """Get user state with rate limiting and retry"""
    for attempt in range(3):
        try:
            return info.user_state(address)
        except Exception as e:
            if attempt == 2:
                logger.error(f"Failed to get user state after 3 attempts: {e}")
                return None
            time.sleep(2 ** attempt)
    return None

    
@rate_limit(2)
def get_trades_history(info: Info, address: str, lookback_hours: int = 24):
    """Get trade history with enhanced error handling and caching"""
    try:
        # Calculate time range
        end_time = int(time.time() * 1000)  
        start_time = end_time - (lookback_hours * 3600 * 1000)
        
        logger.info(f"Fetching trades from {datetime.fromtimestamp(start_time/1000)} to {datetime.fromtimestamp(end_time/1000)}")
        
        trades = info.user_fills_by_time(address, start_time, end_time)
        
        if not trades:
            logger.info(f"No trades found for address {address} in the last {lookback_hours} hours")
            return pd.DataFrame()
        
        logger.info(f"Found {len(trades)} trades")
            
        # Convert to DataFrame
        df = pd.DataFrame(trades)
        
        # Convert timestamps
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        
        # Convert numeric columns
        numeric_columns = ['px', 'sz', 'closedPnl', 'fee']
        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        # Calculate additional metrics
        df['notional'] = df['px'] * df['sz']
        df['net_pnl'] = df['closedPnl'] - df['fee']
        
        # Sort by time
        df = df.sort_values('time', ascending=False)
        
        return df
    
    except Exception as e:
        logger.error(f"Error getting trade history: {e}")
        return pd.DataFrame()

def calculate_pnl_metrics(df: pd.DataFrame):
    """Calculate various PnL metrics with safety checks"""
    default_metrics = {
        'total_pnl': 0.0,
        'total_fees': 0.0,
        'net_pnl': 0.0,
        'win_rate': 0.0,
        'avg_win': 0.0,
        'avg_loss': 0.0
    }
    
    if df is None or len(df) == 0:
        return default_metrics
        
    try:  
        metrics = {
            'total_pnl': df['closedPnl'].sum(),
            'total_fees': df['fee'].sum(),
            'net_pnl': df['net_pnl'].sum(),
            'win_rate': (df['net_pnl'] > 0).mean() * 100,
            'avg_win': df[df['net_pnl'] > 0]['net_pnl'].mean() if len(df[df['net_pnl'] > 0]) > 0 else 0,
            'avg_loss': abs(df[df['net_pnl'] < 0]['net_pnl'].mean()) if len(df[df['net_pnl'] < 0]) > 0 else 0
        }
        
        return metrics
    except Exception as e:
        logger.error(f"Error calculating PnL metrics: {e}")
        return default_metrics

def create_pnl_chart(df: pd.DataFrame):
    """Create cumulative PnL chart with enhanced visualization"""
    if len(df) == 0:
        return None
        
    # Calculate cumulative metrics
    df = df.sort_values('time')
    df['cumulative_pnl'] = df['net_pnl'].cumsum()
    df['cumulative_fees'] = df['fee'].cumsum()
    
    # Create figure
    fig = go.Figure()
    
    # Add PnL line
    fig.add_trace(
        go.Scatter(
            x=df['time'],
            y=df['cumulative_pnl'],
            mode='lines',
            name='Cumulative PnL',
            line=dict(
                color='green' if df['cumulative_pnl'].iloc[-1] >= 0 else 'red',
                width=2
            )
        )
    )
    
    # Add fees line
    fig.add_trace(
        go.Scatter(
            x=df['time'],
            y=-df['cumulative_fees'],
            mode='lines',
            name='Cumulative Fees',
            line=dict(color='grey', width=1, dash='dot')
        )
    )
    
    # Update layout
    fig.update_layout(
        title='Cumulative PnL & Fees',
        xaxis_title='Time',
        yaxis_title='USD',
        height=400,
        hovermode='x unified',
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        )
    )
    
    return fig

def format_trade_row(row):
    """Format trade data for display"""
    return {
        'Time': row['time'].strftime('%Y-%m-%d %H:%M:%S'),
        'Side': 'BUY' if row['side'] == 'B' else 'SELL',
        'Price': f"${row['px']:.2f}",
        'Size': f"{row['sz']:.4f}",
        'PnL': f"${row['closedPnl']:.2f}",
        'Net PnL': f"${row['net_pnl']:.2f}",
    }

def main():
    try:
        config = st.session_state.config
    except Exception as e:
        st.error(f"Configuration error: {str(e)}")
        st.stop()
    
    # Page config
    st.set_page_config(
        page_title='Operator Dashboard',
        page_icon='🤖',
        layout='wide'
    )

    # Just show the network status
    network_color = "yellow" if config.is_testnet else "lime"
    network_name = "Testnet" if config.is_testnet else "Mainnet"
    
    # Right-aligned network status
    st.markdown(f"""
        <p style='text-align: right; padding: 0.5rem 0; color: {network_color}; font-weight: 500;'>
            {config.asset} on {network_name}
        </p>
    """, unsafe_allow_html=True)

    # Initialize connection with correct network
    try:
        info = Info(config.exchange_url)
        metrics_tracker = MetricsTracker(info, config.account_address)
    except Exception as e:
        st.error(f"Failed to initialize connection: {e}")
        return

    # Add CSS (rest of the CSS styling remains the same)
    st.markdown("""
        <style>
        /* Modern typography and spacing */
        .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
        }
        
        /* Header styling */
        h1, h2, h3 {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            color: #1E293B;
            font-weight: 600;
            letter-spacing: -0.5px;
        }
        
        /* Metrics container styling */
        div[data-testid="stMetric"] {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 1rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            transition: all 0.2s ease;
        }
        
        /* Hover state for metric containers */
        div[data-testid="stMetric"]:hover {
            background-color: #0F172A;
            border-color: #1E293B;
            transform: translateY(-2px);
        }
        
        div[data-testid="stMetric"] label {
            color: #64748B !important;
            font-size: 0.875rem !important;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.025em;
            transition: color 0.2s ease;
        }
        
        div[data-testid="stMetric"]:hover label {
            color: #94A3B8 !important;
        }
        
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: #0F172A !important;
            font-size: 1.5rem !important;
            font-weight: 600;
            transition: color 0.2s ease;
        }
        
        div[data-testid="stMetric"]:hover [data-testid="stMetricValue"] {
            color: #FFFFFF !important;
        }
        
        div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
            color: #64748B !important;
            font-size: 0.875rem !important;
            transition: color 0.2s ease;
        }
        
        div[data-testid="stMetric"]:hover [data-testid="stMetricDelta"] {
            color: #94A3B8 !important;
        }
        
        /* Table styling */
        div[data-testid="stTable"] {
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            overflow: hidden;
        }
        
        /* Chart container styling */
        div[data-testid="stPlotlyChart"] {
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 1rem;
            background: white;
        }
        </style>
    """, unsafe_allow_html=True)

    # Modern header with subtitle
    st.markdown(f"""
        <div style='padding: 1rem 0; margin-bottom: 2rem;'>
            <h1 style='color: #0F172A; font-size: 2.25rem; font-weight: 600; margin-bottom: 0.5rem;'>
                HYDRA Dash
            </h1>
            <p style='color: #64748B; font-size: 1rem; font-weight: 400;'>
                Trading {config.asset} on {'Testnet' if config.is_testnet else 'Mainnet'}
            </p>
        </div>
    """, unsafe_allow_html=True)

    # Initialize connection
    try:
        info = Info(config.exchange_url)
        metrics_tracker = MetricsTracker(info, config.account_address)
    except Exception as e:
        st.error(f"Failed to initialize connection: {e}")
        return

    try:
        # Get market data
        market_data = get_market_data(info, config)
        if not market_data:
            st.warning("Unable to fetch market data. Using cached values if available.")
            market_data = st.session_state.get('last_market_data', {
                'price': 0,
                'volume_24h': 0,
                'funding_rate': 0,
                'open_interest': 0
            })
        else:
            st.session_state['last_market_data'] = market_data

        # Get account data
        user_state = get_user_state(info, config.account_address)
        if not user_state:
            account_value = st.session_state.get('last_account_value', 0)
        else:
            account_value = float(user_state['marginSummary']['accountValue'])
            st.session_state['last_account_value'] = account_value

        # Display key metrics in columns with enhanced styling
        col1, col2, col3, col4, col5 = st.columns(5)

        # Get position details
        pos = 0
        entry_price = 0
        leverage = 1
        for position in user_state.get('assetPositions', []):
            if position['position']['coin'] == config.asset:
                pos = float(position['position']['szi'])
                entry_price = float(position['position'].get('entryPx', 0))
                leverage = float(position['position']['leverage'].get('value', 1))
                break

        # Calculate position PnL if we have a position
        position_pnl = 0
        if pos != 0 and entry_price != 0:
            position_pnl = (market_data['price'] - entry_price) * pos

        with col1:
            st.metric(
                'Account Value',
                f"${account_value:,.2f}",
                delta=f"${position_pnl:,.2f} PnL" if position_pnl != 0 else None,
                delta_color="normal" if position_pnl >= 0 else "inverse"
            )

        with col2:
            st.metric(
                f'{config.asset} Price',
                f"${market_data['price']:,.2f}",
                delta=f"{market_data['funding_rate']:.3%} funding/hr",
                delta_color="inverse" if market_data['funding_rate'] < 0 else "normal"
            )

        with col3:
            notional_value = abs(pos * market_data['price'])
            st.metric(
                'Position',
                f"{pos:,.3f} {config.asset}",
                delta=f"${notional_value:,.2f} Value",
                delta_color="off" if pos == 0 else "normal"
            )

        with col4:
            st.metric(
                'Leverage',
                f"{leverage}x",
                delta=f"{(notional_value/account_value):,.2%} Used" if account_value > 0 else "0% Used",
                delta_color="inverse" if leverage > 3 else "normal"
            )

        with col5:
            st.metric(
                'Market Activity',
                f"${market_data['volume_24h']:,.0f} Vol",
                delta=f"${market_data['open_interest']:,.0f} OI",
                delta_color="off"
            )
            
        # Add market context section
        st.subheader('Market Context')
        ctx1, ctx2, ctx3 = st.columns(3)
        
        with ctx1:
            # Funding stats
            st.markdown('### Funding Stats')
            funding_color = 'red' if market_data['funding_rate'] < 0 else 'green'
            st.markdown(f"""
                - Hourly Rate: <span style='color:{funding_color}'>{market_data['funding_rate']:.3%}</span>
                - Daily Rate: <span style='color:{funding_color}'>{market_data['funding_rate']*24:.2%}</span>
                - Weekly Rate: <span style='color:{funding_color}'>{market_data['funding_rate']*24*7:.2%}</span>
            """, unsafe_allow_html=True)
            
        with ctx2:
            # Position info if exists
            st.markdown('### Position Details')
            if pos != 0:
                pnl_color = 'green' if position_pnl >= 0 else 'red'
                st.markdown(f"""
                    - Entry Price: ${entry_price:.4f}
                    - Current PnL: <span style='color:{pnl_color}'>${position_pnl:.2f}</span>
                    - Size: {abs(pos):.4f} {config.asset}
                    - Side: {'Long' if pos > 0 else 'Short'}
                """, unsafe_allow_html=True)
            else:
                st.markdown("*No active position*")
                
        with ctx3:
            # Risk metrics
            st.markdown('### Risk Metrics')
            # Add safety checks for division by zero
            margin_usage = (notional_value/account_value if account_value > 0 else 0)
            available_balance = (account_value - notional_value/leverage if account_value > 0 and leverage > 0 else 0)
            st.markdown(f"""
                - Margin Usage: {margin_usage:.2%}
                - Available Balance: ${available_balance:.2f}
                - Open Interest: ${market_data['open_interest']:,.0f}
            """, unsafe_allow_html=True)


        # Get trade history
        trades_df = get_trades_history(info, config.account_address)

        if trades_df is not None and not trades_df.empty:
            # Display PnL chart
            fig = create_pnl_chart(trades_df)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
            
            # Calculate and display PnL metrics
            metrics = calculate_pnl_metrics(trades_df)
            
            # Create metrics columns
            m1, m2, m3, m4 = st.columns(4)
            
            with m1:
                st.metric("Net PnL", f"${metrics['net_pnl']:,.2f}")
            with m2:
                st.metric("Win Rate", f"{metrics['win_rate']:.1f}%")
            with m3:
                st.metric("Avg Win", f"${metrics['avg_win']:,.2f}")
            with m4:
                st.metric("Avg Loss", f"${metrics['avg_loss']:,.2f}")
            
            # Display recent trades
            st.subheader("Recent Trades")
            
            # Format trades for display
            recent_trades = trades_df.head(10).apply(format_trade_row, axis=1).tolist()
            
            # Create DataFrame for display
            display_df = pd.DataFrame(recent_trades)
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No trades found in the selected time period. Your trading activity will appear here once you start trading.")

        # Add refresh button
        if st.button('Refresh Data'):
            time.sleep(1)  # Rate limit refreshes
            st.experimental_rerun()

        # Show last update time
        st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        st.error(f"An error occurred: {str(e)}")

if __name__ == '__main__':
    main()