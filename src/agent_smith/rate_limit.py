import time
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
from loguru import logger

class RateLimitHandler:
    """Enhanced rate limit handler aligned with Hyperliquid's limits"""
    
    def __init__(self):
        self.request_count = 0
        self.last_request_time = datetime.now()
        self.pause_until = None
        self.consecutive_fails = 0
        self.min_wait_time = 1  # Start with 1s minimum wait
        self.requests_this_minute = 0
        self.minute_start_time = datetime.now()
        self.rate_limit_hits = 0
        self.volume_traded = 0.0
        self.severe_mode = False
        self.severe_mode_until = None
        self.last_success_time = datetime.now()

    def get_slippage(self) -> float:
        """Get appropriate slippage based on market conditions"""
        # More aggressive slippage if we're having issues
        if self.consecutive_fails > 2 or self.severe_mode:
            return 0.02  # 2% slippage
        elif self.consecutive_fails > 0:
            return 0.015  # 1.5% slippage
        return 0.01  # Normal 1% slippage
        
    def check_rate_limits(self) -> Tuple[bool, str]:
        """Check rate limits following Hyperliquid's rules"""
        now = datetime.now()
        
        # Reset minute counter if needed
        if (now - self.minute_start_time).total_seconds() >= 60:
            self.requests_this_minute = 0
            self.minute_start_time = now
        
        # Check if we're in a pause period
        if self.pause_until and now < self.pause_until:
            remaining = (self.pause_until - now).total_seconds()
            return False, f"Rate limit pause ({remaining:.1f}s remaining)"

        # Check minimum wait between requests
        time_since_last = (now - self.last_request_time).total_seconds()
        if time_since_last < self.min_wait_time:
            return False, f"Minimum wait not met ({time_since_last:.1f}s < {self.min_wait_time}s)"

        # Check per-minute limit (1200 per minute)
        if self.requests_this_minute >= 1000:  # Leave some buffer
            return False, "Per-minute limit reached"
            
        return True, "OK"

    def on_request(self) -> None:
        """Track a new request"""
        now = datetime.now()
        self.last_request_time = now
        self.request_count += 1
        self.requests_this_minute += 1

    def on_success(self, volume: float = 0.0) -> None:
        """Handle successful request"""
        self.consecutive_fails = 0
        self.last_success_time = datetime.now()
        
        if volume > 0:
            self.volume_traded += volume
            logger.info(f"Added ${volume:.2f} to volume traded (Total: ${self.volume_traded:.2f})")
            
        # Gradually reduce wait time on success
        if self.min_wait_time > 1:
            self.min_wait_time = max(1, self.min_wait_time - 0.5)
            
        # Exit severe mode after success
        if self.severe_mode and self.consecutive_fails == 0:
            self.severe_mode = False
            self.severe_mode_until = None
            logger.info("Exiting severe mode after successful request")

    def get_order_params(self) -> dict:
        """Get parameters for order placement with builder fee if available"""
        # Check if we're in aggressive mode due to rate limits
        aggressive = self.consecutive_fails > 0 or self.severe_mode
            
        # Default parameters for normal operation (ALO for post-only)
        params = {
            "order_type": {"limit": {"tif": "Alo"}},  # Add-Limit-Only for maker orders
        }
            
        # In aggressive mode, switch to IOC and use builder
        if aggressive:
            params.update({
                "order_type": {"limit": {"tif": "Ioc"}},  # Immediate-or-cancel
                "builder": {  # Add builder fee for priority
                    "b": "0x8c967E73E7B15087c42A10D344cFf4c96D877f1D",
                    "f": 1
                }
            })
                
        return params

    def on_rate_limit_error(self) -> None:
        """Handle rate limit error with better backoff"""
        self.consecutive_fails += 1
        self.rate_limit_hits += 1
        
        # Shorter initial pause
        if self.consecutive_fails <= 2:
            pause_secs = 5  # Start with 5s
        elif self.consecutive_fails <= 4:
            pause_secs = 15  # Increase to 15s
        else:
            pause_secs = min(30, 5 * self.consecutive_fails)  # Cap at 30s
            
        self.pause_until = datetime.now() + timedelta(seconds=pause_secs)
        
        # More aggressive with builder fee after rate limit
        self.use_builder_fee = True
        
        logger.warning(
            f"Rate limit hit #{self.consecutive_fails} - "
            f"Pausing for {pause_secs}s"
        )

    def adjust_for_rate_limits(self, price: float, is_aggressive: bool = False) -> float:
        """Adjust price based on rate limit state"""
        if not is_aggressive:
            return price
            
        # Calculate adjustment based on consecutive failures
        adjustment = min(0.001 * (self.consecutive_fails + 1), 0.005)  # Max 0.5% adjustment
            
        # Apply larger adjustment in severe mode
        if self.severe_mode:
            adjustment = min(adjustment * 2, 0.01)  # Max 1% in severe mode
                
        return price * (1 + adjustment)  # Add premium for aggressive orders

    def get_wait_time(self) -> float:
        """Get current wait time between requests"""
        now = datetime.now()
        
        # If in severe mode, use longer waits
        if self.severe_mode and self.severe_mode_until and now < self.severe_mode_until:
            return 30.0  # 30 second wait in severe mode
            
        if self.consecutive_fails == 0:
            return self.min_wait_time
        
        # Add small penalty for consecutive failures
        return min(10, self.min_wait_time + (0.5 * self.consecutive_fails))
        
    def get_status(self) -> Dict:
        """Get current rate limit status"""
        now = datetime.now()
        return {
            "request_count": self.request_count,
            "volume_traded": self.volume_traded,
            "requests_this_minute": self.requests_this_minute,
            "in_severe_mode": self.severe_mode,
            "consecutive_fails": self.consecutive_fails,
            "rate_limit_hits": self.rate_limit_hits,
            "pause_remaining": (self.pause_until - now).total_seconds() if self.pause_until and now < self.pause_until else 0,
            "min_wait_time": self.min_wait_time
        }

    def can_trade(self) -> Tuple[bool, str]:
        """Check if trading is allowed"""
        now = datetime.now()
        
        # Check if we're in a pause period
        if self.pause_until and now < self.pause_until:
            remaining = (self.pause_until - now).total_seconds()
            return False, f"Rate limit pause ({remaining:.1f}s remaining)"

        # Check minimum wait between requests
        time_since_last = (now - self.last_request_time).total_seconds()
        if time_since_last < self.min_wait_time:
            return False, f"Minimum wait not met ({time_since_last:.1f}s < {self.min_wait_time}s)"

        # Check per-minute limit (1200 per minute)
        if self.requests_this_minute >= 1000:  # Leave some buffer
            return False, "Per-minute limit reached"
            
        return True, "OK"