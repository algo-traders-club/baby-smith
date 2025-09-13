from typing import Optional
import os
from dotenv import load_dotenv
from loguru import logger

from agent_smith.agent import AgentSmith
from agent_smith.config import TradingConfig
from agent_smith.logging_utils import (
    setup_logging,
    print_startup_banner,
    print_status_update,
    console
)

# Load environment variables
load_dotenv()

# Create configuration using the new factory method
def initialize_config() -> TradingConfig:
    # Validate required environment variables
    required_vars = ['HL_ACCOUNT_ADDRESS', 'HL_SECRET_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    # Create configuration from environment
    config = TradingConfig.from_env()
    
    # Log configuration (excluding sensitive data)
    logger.info(f"Initialized configuration for {config.asset} on "
                f"{'testnet' if config.is_testnet else 'mainnet'}")
    logger.debug(f"Max position: {config.max_position}")
    logger.debug(f"Base position: {config.base_position}")
    logger.debug(f"Leverage: {config.leverage}x")
    
    return config

def main() -> None:
    # Setup logging
    setup_logging()
    print_startup_banner()
    
    try:
        # Initialize configuration
        config = initialize_config()
        
        # Initialize agent
        console.print("[cyan]Initializing Agent Smith...[/]")
        agent = AgentSmith(config)
        
        # Check wallet balance
        user_state = agent.info.user_state(config.account_address)
        logger.debug(f"User state: {user_state}")
        
        if 'marginSummary' in user_state:
            account_value = float(user_state['marginSummary'].get('accountValue', 0))
            logger.info(f"Account value: ${account_value:,.2f}")
        else:
            logger.error("Could not find marginSummary in user state")
        
        # Print initial status
        initial_state = {
            'account_value': account_value if 'account_value' in locals() else 0,
            'position': agent.position or 0,
            'asset': config.asset,
            'current_price': float(agent.info.all_mids().get(config.asset, 0)),
            'volume': 0,
            'pnl': 0
        }
        print_status_update(initial_state)
        
        # Run the agent
        console.print("\n[cyan]Starting perpetual trading engine...[/]")
        agent.run()
        
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        raise

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down gracefully...[/]")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        console.print(f"\n[red]Fatal error: {str(e)}[/]")
        raise