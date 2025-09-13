"""
Data fetching components for the dashboard.
"""

import pandas as pd
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from hyperliquid.info import Info
from loguru import logger
from functools import wraps
import time

from agent_smith.config import TradingConfig
from agent_smith.exceptions import MarketDataException


def rate_limit(seconds: int):
    """Decorator to rate limit function calls."""
    def decorator(func):
        last_called = {'time': 0}
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called['time']
            if elapsed < seconds:
                time.sleep(seconds - elapsed)
            result = func(*args, **kwargs)
            last_called['time'] = time.time()
            return result
        return wrapper
    return decorator


class DashboardDataFetcher:
    """Handles all data fetching for the dashboard."""
    
    def __init__(self, info: Info, config: TradingConfig):
        self.info = info
        self.config = config
        
    @rate_limit(2)
    def get_market_data(self) -> Dict[str, Any]:
        """Get current market data for the configured asset."""
        try:
            # Get L2 orderbook data
            l2_snapshot = self.info.l2_snapshot(self.config.asset)
            if not l2_snapshot or 'levels' not in l2_snapshot:
                raise MarketDataException("Failed to get L2 snapshot")
                
            levels = l2_snapshot['levels']
            if not levels or len(levels) < 2:
                raise MarketDataException("Insufficient market depth")
                
            bids = levels[0]
            asks = levels[1]
            
            if not bids or not asks:
                raise MarketDataException("No bids or asks available")
                
            best_bid = float(bids[0]['px'])
            best_ask = float(asks[0]['px'])
            
            # Calculate derived metrics
            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2
            spread_bps = (spread / mid_price) * 10000 if mid_price > 0 else 0
            
            return {
                'asset': self.config.asset,
                'best_bid': best_bid,
                'best_ask': best_ask,
                'spread': spread,
                'spread_bps': spread_bps,
                'mid_price': mid_price,
                'timestamp': datetime.now(),
                'bid_size': float(bids[0]['sz']) if bids else 0,
                'ask_size': float(asks[0]['sz']) if asks else 0
            }
            
        except Exception as e:
            logger.error(f"Error fetching market data: {e}")
            raise MarketDataException(f"Market data fetch failed: {e}")
            
    @rate_limit(3)
    def get_user_state(self, address: str) -> Dict[str, Any]:
        """Get comprehensive user state information."""
        try:
            user_state = self.info.user_state(address)
            if not user_state:
                raise MarketDataException("Failed to get user state")
                
            # Extract margin summary
            margin_summary = user_state.get('marginSummary', {})
            account_value = float(margin_summary.get('accountValue', '0'))
            total_margin_used = float(margin_summary.get('totalMarginUsed', '0'))
            total_ntl_pos = float(margin_summary.get('totalNtlPos', '0'))
            
            # Extract position information
            positions = []
            asset_positions = user_state.get('assetPositions', [])
            
            for pos in asset_positions:
                position_data = pos.get('position', {})
                if position_data:
                    positions.append({
                        'coin': position_data.get('coin', ''),
                        'size': float(position_data.get('szi', '0')),
                        'entry_price': float(position_data.get('entryPx', '0')),
                        'unrealized_pnl': float(position_data.get('unrealizedPnl', '0')),
                        'return_on_equity': float(position_data.get('returnOnEquity', '0'))
                    })
                    
            # Find current asset position
            current_position = 0.0
            entry_price = 0.0
            unrealized_pnl = 0.0
            
            for pos in positions:
                if pos['coin'] == self.config.asset:
                    current_position = pos['size']
                    entry_price = pos['entry_price']
                    unrealized_pnl = pos['unrealized_pnl']
                    break
                    
            return {
                'account_value': account_value,
                'total_margin_used': total_margin_used,
                'total_ntl_pos': total_ntl_pos,
                'margin_ratio': (total_margin_used / account_value) if account_value > 0 else 0,
                'current_position': current_position,
                'entry_price': entry_price,
                'unrealized_pnl': unrealized_pnl,
                'all_positions': positions,
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"Error fetching user state: {e}")
            raise MarketDataException(f"User state fetch failed: {e}")
            
    @rate_limit(5)
    def get_trades_history(self, address: str, lookback_hours: int = 24) -> pd.DataFrame:
        """Get trading history and convert to DataFrame."""
        try:
            # Get user fills from the API
            fills = self.info.user_fills(address)
            
            if not fills:
                logger.info("No trade history found")
                return pd.DataFrame()
                
            # Convert to DataFrame
            df = pd.DataFrame(fills)
            
            # Convert timestamp and filter by lookback period
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
            df = df[df['time'] >= cutoff_time]
            
            if df.empty:
                logger.info(f"No trades found in the last {lookback_hours} hours")
                return df
                
            # Clean and convert numeric columns
            numeric_columns = ['px', 'sz', 'fee', 'closedPnl']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    
            # Add calculated columns
            df['notional'] = df['px'] * df['sz']
            df['side'] = df['dir'].map({'Buy': 'BUY', 'Sell': 'SELL'})
            
            # Sort by time
            df = df.sort_values('time', ascending=False)
            
            # Filter for current asset if specified
            if self.config.asset and 'coin' in df.columns:
                df = df[df['coin'] == self.config.asset]
                
            return df
            
        except Exception as e:
            logger.error(f"Error fetching trade history: {e}")
            return pd.DataFrame()
            
    def calculate_pnl_metrics(self, trades_df: pd.DataFrame) -> Dict[str, float]:
        """Calculate PnL metrics from trades DataFrame."""
        try:
            if trades_df.empty:
                return {
                    'total_pnl': 0.0,
                    'total_trades': 0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'win_rate': 0.0,
                    'avg_win': 0.0,
                    'avg_loss': 0.0,
                    'total_fees': 0.0,
                    'total_volume': 0.0
                }
                
            # Calculate basic metrics
            total_pnl = trades_df['closedPnl'].sum() if 'closedPnl' in trades_df.columns else 0.0
            total_trades = len(trades_df)
            total_fees = trades_df['fee'].sum() if 'fee' in trades_df.columns else 0.0
            total_volume = trades_df['notional'].sum() if 'notional' in trades_df.columns else 0.0
            
            # Calculate win/loss metrics
            if 'closedPnl' in trades_df.columns:
                winning_trades = len(trades_df[trades_df['closedPnl'] > 0])
                losing_trades = len(trades_df[trades_df['closedPnl'] < 0])
                win_rate = (winning_trades / total_trades) if total_trades > 0 else 0.0
                
                wins = trades_df[trades_df['closedPnl'] > 0]['closedPnl']
                losses = trades_df[trades_df['closedPnl'] < 0]['closedPnl']
                
                avg_win = wins.mean() if len(wins) > 0 else 0.0
                avg_loss = losses.mean() if len(losses) > 0 else 0.0
            else:
                winning_trades = 0
                losing_trades = 0
                win_rate = 0.0
                avg_win = 0.0
                avg_loss = 0.0
                
            return {
                'total_pnl': total_pnl,
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'win_rate': win_rate,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'total_fees': total_fees,
                'total_volume': total_volume
            }
            
        except Exception as e:
            logger.error(f"Error calculating PnL metrics: {e}")
            return {}
            
    def get_performance_summary(self, address: str, lookback_hours: int = 24) -> Dict[str, Any]:
        """Get comprehensive performance summary."""
        try:
            # Get trade history
            trades_df = self.get_trades_history(address, lookback_hours)
            
            # Calculate PnL metrics
            pnl_metrics = self.calculate_pnl_metrics(trades_df)
            
            # Get current user state
            user_state = self.get_user_state(address)
            
            # Combine metrics
            performance = {
                **pnl_metrics,
                'account_value': user_state.get('account_value', 0),
                'current_position': user_state.get('current_position', 0),
                'unrealized_pnl': user_state.get('unrealized_pnl', 0),
                'margin_ratio': user_state.get('margin_ratio', 0),
                'lookback_hours': lookback_hours,
                'last_update': datetime.now()
            }
            
            return performance
            
        except Exception as e:
            logger.error(f"Error getting performance summary: {e}")
            return {}
            
    def validate_data_quality(self, data: Dict) -> bool:
        """Validate data quality before displaying."""
        try:
            required_fields = ['timestamp']
            
            for field in required_fields:
                if field not in data:
                    logger.warning(f"Missing required field: {field}")
                    return False
                    
            # Check for reasonable timestamp (not too old)
            if 'timestamp' in data:
                timestamp = data['timestamp']
                if isinstance(timestamp, datetime):
                    age = datetime.now() - timestamp
                    if age.total_seconds() > 300:  # 5 minutes
                        logger.warning(f"Data is {age.total_seconds():.0f}s old")
                        return False
                        
            return True
            
        except Exception as e:
            logger.error(f"Error validating data quality: {e}")
            return False