from pydantic import BaseModel
from typing import Optional
import os
from hyperliquid.utils import constants

class TradingConfig(BaseModel):
    # Required credentials
    account_address: str
    secret_key: str
    
    # Trading configuration
    asset: str = "HYPE"
    max_position: float = 5.0
    base_position: float = 1.0
    min_spread: float = 0.002
    min_order_interval: int = 30
    profit_take_threshold: float = 0.01
    stop_loss_threshold: float = 0.02
    volatility_window: int = 100
    max_open_orders: int = 4
    leverage: int = 3
    
    # Exchange settings
    exchange_url: str = constants.TESTNET_API_URL  # Added this line
    is_testnet: bool = True  # Added for network tracking
    
    @classmethod
    def from_env(cls):
        """Create configuration from environment variables"""
        # Choose network
        is_testnet = os.getenv("HL_TESTNET", "true").lower() == "true"
        exchange_url = constants.TESTNET_API_URL if is_testnet else constants.MAINNET_API_URL
        
        return cls(
            # Required credentials
            account_address=os.getenv("HL_ACCOUNT_ADDRESS"),
            secret_key=os.getenv("HL_SECRET_KEY"),
            
            # Exchange settings
            exchange_url=exchange_url,
            is_testnet=is_testnet,
            
            # Trading settings - all optional with defaults
            asset=os.getenv("HL_ASSET", "HYPE"),
            max_position=float(os.getenv("HL_MAX_POSITION", "5.0")),
            base_position=float(os.getenv("HL_BASE_POSITION", "1.0")),
            min_spread=float(os.getenv("HL_MIN_SPREAD", "0.002")),
            min_order_interval=int(os.getenv("HL_MIN_ORDER_INTERVAL", "30")),
            profit_take_threshold=float(os.getenv("HL_PROFIT_TAKE_THRESHOLD", "0.01")),
            stop_loss_threshold=float(os.getenv("HL_STOP_LOSS_THRESHOLD", "0.02")), 
            volatility_window=int(os.getenv("HL_VOLATILITY_WINDOW", "100")),
            max_open_orders=int(os.getenv("HL_MAX_OPEN_ORDERS", "4")),
            leverage=int(os.getenv("HL_LEVERAGE", "3"))
        )