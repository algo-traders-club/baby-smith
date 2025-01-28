import sys
from datetime import datetime
from typing import Dict, Any, Optional

from loguru import logger
from rich.console import Console
from rich.theme import Theme

# Create rich console with custom theme
console = Console(theme=Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "red bold",
    "success": "green",
    "highlight": "magenta",
    "timestamp": "dim cyan",
    "price": "bright_green",
    "volume": "bright_blue",
    "position": "bright_yellow"
}))

def print_startup_banner():
    """Print a styled startup banner"""
    console.print("\n")
    console.print("=" * 80, style="cyan")
    console.print(" " * 30 + "[bold cyan]AGENT SMITH v1.0[/]")
    console.print(" " * 25 + "[dim cyan]HyperLiquid Trading Agent[/]")
    console.print("=" * 80, style="cyan")
    console.print("\n")

def format_number(num: float, decimals: int = 2) -> str:
    """Format number with thousand separators and fixed decimals"""
    return f"{num:,.{decimals}f}"

def setup_logging():
    """Configure logging with custom format and handlers"""
    # Remove default handler
    logger.remove()
    
    # Add custom handler for file logging
    logger.add(
        "logs/agent_smith_{time:YYYY-MM-DD}.log",
        rotation="12:00",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        level="DEBUG"
    )
    
    # Add custom handler for console output
    logger.add(
        lambda msg: console_handler(msg),
        colorize=True,
        format="{message}",
        level="INFO"
    )

def console_handler(message: Dict[str, Any]):
    """Custom console handler with rich formatting"""
    record = message.record
    time_str = record["time"].strftime("%H:%M:%S")
    level_name = record["level"].name
    
    # Format based on log level and content
    if level_name == "ERROR":
        console.print(f"[timestamp]{time_str}[/] [error]❌ {record['message']}[/]")
    elif level_name == "WARNING":
        console.print(f"[timestamp]{time_str}[/] [warning]⚠️  {record['message']}[/]")
    elif level_name == "SUCCESS":
        console.print(f"[timestamp]{time_str}[/] [success]✅ {record['message']}[/]")
    elif "price" in str(record["message"]).lower():
        format_price_message(time_str, record["message"])
    elif "position" in str(record["message"]).lower():
        format_position_message(time_str, record["message"])
    elif "order" in str(record["message"]).lower():
        format_order_message(time_str, record["message"])
    else:
        console.print(f"[timestamp]{time_str}[/] [info]{record['message']}[/]")

def format_price_message(time_str: str, message: str):
    """Format price-related messages"""
    try:
        if "current price" in message.lower():
            parts = message.split(":")
            price = float(parts[1].strip())
            console.print(
                f"[timestamp]{time_str}[/] [info]Price:[/] [price]${format_number(price)}[/]"
            )
        else:
            console.print(f"[timestamp]{time_str}[/] [info]{message}[/]")
    except Exception:
        console.print(f"[timestamp]{time_str}[/] [info]{message}[/]")

def format_position_message(time_str: str, message: str):
    """Format position-related messages"""
    try:
        if "position" in message.lower():
            if ":" in message:
                label, value = message.split(":")
                console.print(
                    f"[timestamp]{time_str}[/] [info]{label}:[/] [position]{value.strip()}[/]"
                )
            else:
                console.print(f"[timestamp]{time_str}[/] [position]{message}[/]")
        else:
            console.print(f"[timestamp]{time_str}[/] [info]{message}[/]")
    except Exception:
        console.print(f"[timestamp]{time_str}[/] [info]{message}[/]")

def format_order_message(time_str: str, message: str):
    """Format order-related messages"""
    try:
        if "success" in message.lower():
            console.print(f"[timestamp]{time_str}[/] [success]{message}[/]")
        elif "cancelled" in message.lower():
            console.print(f"[timestamp]{time_str}[/] [warning]{message}[/]")
        elif "failed" in message.lower():
            console.print(f"[timestamp]{time_str}[/] [error]{message}[/]")
        else:
            console.print(f"[timestamp]{time_str}[/] [info]{message}[/]")
    except Exception:
        console.print(f"[timestamp]{time_str}[/] [info]{message}[/]")

def format_debug_state(book_msg: Dict, market_state: Optional[Dict] = None) -> str:
    """Format detailed debug state information"""
    debug_str = "\nDEBUG STATE\n" + "-" * 40 + "\n"
    
    try:
        if book_msg and 'levels' in book_msg:
            bids = book_msg['levels'][0] if len(book_msg['levels']) > 0 else []
            asks = book_msg['levels'][1] if len(book_msg['levels']) > 1 else []
            
            debug_str += "ORDER BOOK:\n"
            if len(bids) > 0:
                debug_str += f"Best Bid: ${float(bids[0]['px']):.4f} x {float(bids[0]['sz']):.4f}\n"
            if len(asks) > 0:
                debug_str += f"Best Ask: ${float(asks[0]['px']):.4f} x {float(asks[0]['sz']):.4f}\n"
                
            debug_str += f"Bid Levels: {len(bids)}, Ask Levels: {len(asks)}\n"
        
        if market_state:
            debug_str += "\nMARKET STATE:\n"
            for key, value in market_state.items():
                debug_str += f"{key}: {value}\n"
                
    except Exception as e:
        debug_str += f"\nError formatting debug state: {str(e)}\n"
        
    debug_str += "-" * 40
    return debug_str

def setup_debug_logging():
    """Setup additional debug logging handlers"""
    logger.add(
        "logs/debug_{time:YYYY-MM-DD}.log",
        rotation="12:00",
        retention="3 days",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        level="DEBUG",
        filter=lambda record: record["level"].name == "DEBUG"
    )

def print_status_update(state: Dict[str, Any]):
    """Print a formatted status update"""
    console.print("\n[cyan]Status Update[/]")
    console.print("-" * 40, style="dim cyan")
    
    # Format account info
    console.print(f"Account Value: [green]${format_number(state['account_value'])}[/]")
    console.print(f"Position    : [yellow]{format_number(state['position'], 4)} {state['asset']}[/]")
    
    # Format market info
    console.print(f"Current Price: [green]${format_number(state['current_price'])}[/]")
    console.print(f"24h Volume  : [blue]${format_number(state['volume'])}[/]")
    
    # Format performance
    pnl = state.get('pnl', 0)
    pnl_color = "green" if pnl >= 0 else "red"
    console.print(f"PnL         : [{pnl_color}]${format_number(pnl)}[/]")
    
    console.print("-" * 40, style="dim cyan")
    console.print("\n")