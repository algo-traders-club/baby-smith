"""
Custom exception hierarchy for the Baby Smith trading agent.

This module provides a comprehensive set of exceptions for different
error scenarios in the trading system.
"""

from typing import Optional, Dict, Any


class TradingException(Exception):
    """Base exception for all trading-related errors."""
    
    def __init__(
        self, 
        message: str, 
        code: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.context = context or {}
        
    def __str__(self) -> str:
        base = self.message
        if self.code:
            base += f" (Code: {self.code})"
        if self.context:
            base += f" Context: {self.context}"
        return base


class MarketDataException(TradingException):
    """Raised when market data retrieval or processing fails."""
    pass


class OrderExecutionException(TradingException):
    """Raised when order placement, modification, or cancellation fails."""
    pass


class RiskManagementException(TradingException):
    """Raised when risk management rules are violated."""
    pass


class ConfigurationException(TradingException):
    """Raised when there are configuration or setup errors."""
    pass


class PositionManagementException(TradingException):
    """Raised when position management operations fail."""
    pass


class RateLimitException(TradingException):
    """Raised when API rate limits are exceeded."""
    pass


class ValidationException(TradingException):
    """Raised when data validation fails."""
    pass


class NetworkException(TradingException):
    """Raised when network-related errors occur."""
    pass


class AuthenticationException(TradingException):
    """Raised when authentication fails."""
    pass


class InsufficientFundsException(TradingException):
    """Raised when there are insufficient funds for an operation."""
    pass