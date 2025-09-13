"""
Market data management module.
"""

from typing import Dict, Optional
from loguru import logger
from hyperliquid.info import Info

from agent_smith.trading_types import PerpMarketState
from agent_smith.config import TradingConfig
from agent_smith.exceptions import MarketDataException


class MarketDataManager:
    """Manages market data retrieval and processing."""
    
    def __init__(self, info: Info, config: TradingConfig):
        self.info = info
        self.config = config
        
    def get_perp_market_state(self) -> Optional[PerpMarketState]:
        """Get current perpetual market state."""
        try:
            # Get market data
            l2_book = self.info.l2_snapshot(self.config.asset)
            if not l2_book or 'levels' not in l2_book:
                logger.error("Failed to get L2 book data")
                return None
                
            levels = l2_book['levels']
            if not levels or len(levels) < 2:
                logger.error("Insufficient market depth")
                return None
                
            # Parse bid/ask data
            bids = levels[0]
            asks = levels[1]
            
            if not bids or not asks:
                logger.error("No bids or asks available")
                return None
                
            best_bid = float(bids[0]['px'])
            best_ask = float(asks[0]['px'])
            
            # Get user state for position
            user_state = self.info.user_state(self.config.account_address)
            if not user_state:
                logger.error("Failed to get user state")
                return None
                
            # Get position
            position = self._get_accurate_position(user_state, self.config.asset)
            
            # Get mark price
            mark_price = (best_bid + best_ask) / 2
            
            # Get all positions for cross margin calculation
            all_positions = user_state.get('assetPositions', [])
            
            return PerpMarketState(
                asset=self.config.asset,
                best_bid=best_bid,
                best_ask=best_ask,
                mark_price=mark_price,
                position=position,
                margin_summary=user_state.get('marginSummary', {}),
                cross_margin_summary=user_state.get('crossMarginSummary', {}),
                all_positions=all_positions
            )
            
        except Exception as e:
            logger.error(f"Error getting market state: {e}")
            raise MarketDataException(f"Failed to retrieve market data: {e}")
            
    def get_accurate_position_state(self, address: str) -> Dict:
        """Get accurate position state with entry price calculation."""
        try:
            user_state = self.info.user_state(address)
            if not user_state:
                raise MarketDataException("Failed to get user state")
                
            position = self._get_accurate_position(user_state, self.config.asset)
            entry_price = None
            
            # Calculate entry price from position data
            asset_positions = user_state.get('assetPositions', [])
            for pos in asset_positions:
                if pos.get('position', {}).get('coin') == self.config.asset:
                    entry_price = float(pos['position'].get('entryPx', 0))
                    break
                    
            return {
                'position': position,
                'entry_price': entry_price,
                'user_state': user_state
            }
            
        except Exception as e:
            logger.error(f"Error getting position state: {e}")
            raise MarketDataException(f"Failed to get position state: {e}")
            
    def _get_accurate_position(self, user_state: Dict, asset: str) -> float:
        """Extract accurate position size from user state."""
        try:
            # Check asset positions
            asset_positions = user_state.get('assetPositions', [])
            for position in asset_positions:
                pos_data = position.get('position', {})
                if pos_data.get('coin') == asset:
                    size_str = pos_data.get('szi', '0')
                    return float(size_str)
                    
            return 0.0
            
        except Exception as e:
            logger.error(f"Error parsing position: {e}")
            return 0.0
            
    def get_position_details(self, user_state: Dict, asset: str) -> Dict[str, float]:
        """Get detailed position information."""
        try:
            asset_positions = user_state.get('assetPositions', [])
            for position in asset_positions:
                pos_data = position.get('position', {})
                if pos_data.get('coin') == asset:
                    return {
                        'size': float(pos_data.get('szi', '0')),
                        'entry_price': float(pos_data.get('entryPx', '0')),
                        'unrealized_pnl': float(pos_data.get('unrealizedPnl', '0')),
                        'return_on_equity': float(pos_data.get('returnOnEquity', '0'))
                    }
                    
            return {
                'size': 0.0,
                'entry_price': 0.0,
                'unrealized_pnl': 0.0,
                'return_on_equity': 0.0
            }
            
        except Exception as e:
            logger.error(f"Error getting position details: {e}")
            return {}
            
    def validate_market_data(self, market_state: PerpMarketState) -> bool:
        """Validate market data quality."""
        try:
            # Check spread reasonableness
            spread = market_state.best_ask - market_state.best_bid
            spread_pct = spread / market_state.best_bid if market_state.best_bid > 0 else float('inf')
            
            if spread_pct > 0.1:  # 10% spread seems unreasonable
                logger.warning(f"Unusually wide spread: {spread_pct:.2%}")
                return False
                
            # Check price reasonableness
            if market_state.best_bid <= 0 or market_state.best_ask <= 0:
                logger.error("Invalid bid/ask prices")
                return False
                
            if market_state.mark_price <= 0:
                logger.error("Invalid mark price")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error validating market data: {e}")
            return False