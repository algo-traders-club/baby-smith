"""
Market maker strategies module.

This module provides market making strategies for perpetual futures trading.
The original AggressiveMarketMaker is now replaced with EnhancedPerpMarketMaker
but is re-exported here for backward compatibility.
"""

from agent_smith.strategies.enhanced_market_maker import EnhancedPerpMarketMaker

# Backward compatibility alias
AggressiveMarketMaker = EnhancedPerpMarketMaker

__all__ = ['AggressiveMarketMaker', 'EnhancedPerpMarketMaker']