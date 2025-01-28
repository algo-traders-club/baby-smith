from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from hyperliquid.info import Info
from loguru import logger

@dataclass
class TradingMetrics:
    '''Trading metrics for Agent Smith'''
    timestamp: datetime
    asset: str
    position_size: float
    entry_price: Optional[float]
    current_price: float
    unrealized_pnl: float
    account_value: float
    margin_used: float
    return_on_equity: float
    
class MetricsTracker:
    '''Track and store trading metrics'''
    
    def __init__(self, info: Info, address: str):
        self.info = info
        self.address = address
        self.metrics_history: List[TradingMetrics] = []
        
    def update_metrics(self) -> TradingMetrics:
        '''Update current trading metrics'''
        try:
            # Get user state
            user_state = self.info.user_state(self.address)
            margin_summary = user_state['marginSummary']
            
            # Get current prices
            current_prices = self.info.all_mids()
            
            metrics = []
            
            # Process each position
            for position in user_state['assetPositions']:
                pos = position['position']
                asset = pos['coin']
                
                metric = TradingMetrics(
                    timestamp=datetime.now(),
                    asset=asset,
                    position_size=float(pos['szi']),
                    entry_price=float(pos.get('entryPx', 0)) if 'entryPx' in pos else None,
                    current_price=float(current_prices[asset]),
                    unrealized_pnl=float(pos['unrealizedPnl']),
                    account_value=float(margin_summary['accountValue']),
                    margin_used=float(pos['marginUsed']),
                    return_on_equity=float(pos['returnOnEquity'])
                )
                
                metrics.append(metric)
                self.metrics_history.append(metric)
            
            return metrics
            
        except Exception as e:
            logger.error(f'Error updating metrics: {e}')
            return []
    
    def get_metrics_df(self) -> pd.DataFrame:
        '''Convert metrics history to DataFrame'''
        return pd.DataFrame([vars(m) for m in self.metrics_history])

    def get_current_positions(self) -> Dict[str, float]:
        '''Get current positions'''
        user_state = self.info.user_state(self.address)
        positions = {}
        for position in user_state['assetPositions']:
            pos = position['position']
            positions[pos['coin']] = float(pos['szi'])
        return positions

    def get_pnl_history(self) -> pd.DataFrame:
        '''Get PnL history'''
        df = self.get_metrics_df()
        if len(df) == 0:
            return pd.DataFrame()
        return df.groupby('timestamp')['unrealized_pnl'].sum().reset_index()