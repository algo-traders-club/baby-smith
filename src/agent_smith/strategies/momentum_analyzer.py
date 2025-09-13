"""
Momentum analysis module for trading strategies.
"""

from typing import List, Optional
from datetime import datetime
import pandas as pd
import numpy as np
from loguru import logger

from agent_smith.exceptions import MarketDataException


class MomentumAnalyzer:
    """Analyzes market momentum using multiple technical indicators."""
    
    def __init__(
        self,
        momentum_window: int = 20,
        momentum_threshold: float = 0.003,
        max_momentum_trades: int = 2
    ):
        self.momentum_window = momentum_window
        self.momentum_threshold = momentum_threshold
        self.max_momentum_trades = max_momentum_trades
        
        self.momentum_prices: List[float] = []
        self.last_momentum_signal: Optional[str] = None
        self.momentum_trades = 0
        self.momentum_reset_time = datetime.now()
        
    def calculate_market_momentum(
        self, 
        mark_price: float, 
        best_bid: float, 
        best_ask: float
    ) -> Optional[str]:
        """Calculate momentum signal with improved direction detection."""
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
            rsi = self._calculate_rsi(prices)
            
            # Mean reversion check
            price_std = prices.std()
            zscore = (mark_price - prices.mean()) / price_std if price_std > 0 else 0
            
            # Calculate order book imbalance
            mid_price = (best_bid + best_ask) / 2
            book_imbalance = (mark_price - mid_price) / mid_price if mid_price > 0 else 0
            
            # Combined signal
            signal_strength = self._calculate_signal_strength(
                short_ema, medium_ema, long_ema, rsi, zscore, book_imbalance
            )
            
            # Determine final signal with stronger thresholds
            if signal_strength > 0.3:  # Stronger threshold for long
                return "long"
            elif signal_strength < -0.3:  # Stronger threshold for short
                return "short"
                
            return None
            
        except Exception as e:
            logger.error(f"Error calculating momentum: {e}")
            raise MarketDataException(f"Momentum calculation failed: {e}")
            
    def calculate_momentum_score(self, mark_price: float) -> Optional[float]:
        """Calculate momentum score using multiple indicators."""
        try:
            self.momentum_prices.append(mark_price)
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
            rsi = self._calculate_rsi(prices)
            
            # Combine signals
            momentum_ema = (fast_ema / slow_ema - 1)
            rsi_signal = (rsi - 50) / 50  # Normalize RSI to [-1, 1]
            
            # Weighted combination
            momentum = 0.7 * momentum_ema + 0.3 * rsi_signal
            
            return momentum
            
        except Exception as e:
            logger.error(f"Error calculating momentum score: {e}")
            return None
            
    def should_trade_momentum(self) -> bool:
        """Check if momentum trading conditions are met."""
        # Reset momentum trades hourly
        if (datetime.now() - self.momentum_reset_time).total_seconds() > 3600:
            self.momentum_trades = 0
            self.momentum_reset_time = datetime.now()
            
        return self.momentum_trades < self.max_momentum_trades
        
    def update_momentum_trade(self) -> None:
        """Update momentum trade counter."""
        self.momentum_trades += 1
        
    def get_volatility_metrics(self) -> dict:
        """Calculate current volatility metrics."""
        if len(self.momentum_prices) < 20:
            return {}
            
        try:
            prices = np.array(self.momentum_prices[-20:])
            volatility = np.std(prices)
            avg_price = np.mean(prices)
            vol_ratio = volatility / avg_price if avg_price > 0 else 0
            
            return {
                'volatility': volatility,
                'avg_price': avg_price,
                'vol_ratio': vol_ratio,
                'is_high_vol': vol_ratio > 0.005  # 0.5% threshold
            }
            
        except Exception as e:
            logger.error(f"Error calculating volatility: {e}")
            return {}
            
    def _calculate_rsi(self, prices: pd.Series, window: int = 14) -> float:
        """Calculate RSI indicator."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs)).iloc[-1]
        return rsi
        
    def _calculate_signal_strength(
        self,
        short_ema: float,
        medium_ema: float,
        long_ema: float,
        rsi: float,
        zscore: float,
        book_imbalance: float
    ) -> float:
        """Calculate combined signal strength."""
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
        
        return signal_strength