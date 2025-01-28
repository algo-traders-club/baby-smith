from hyperliquid.utils import constants
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
import eth_account
from agent_smith.config import config
from loguru import logger

def check_wallet_connection():
    """Diagnostic check of wallet connection"""
    try:
        # Initialize clients
        info = Info(config.exchange_url)
        wallet = eth_account.Account.from_key(config.secret_key)
        
        print("\n=== CONNECTION INFO ===")
        print(f"Exchange URL: {config.exchange_url}")
        print(f"Account Address: {config.account_address}")
        print(f"Wallet Address: {wallet.address}")
        
        if config.account_address.lower() != wallet.address.lower():
            print("\n⚠️  WARNING: Account address doesn't match wallet address!")
            print("This means you're using an API key/wallet different from your main account.")
            print("Make sure the API wallet has proper permissions.")
        
        # Check basic market data access
        print("\n=== MARKET ACCESS CHECK ===")
        try:
            market_data = info.all_mids()
            print("✅ Can access market data")
            if 'PURR/USDC' in market_data:
                print(f"Current PURR price: ${float(market_data['PURR/USDC']):.4f}")
        except Exception as e:
            print(f"❌ Cannot access market data: {str(e)}")
        
        # Try to get all spot assets
        print("\n=== SPOT ASSETS CHECK ===")
        try:
            spot_meta = info.spot_meta()
            spot_assets = spot_meta.get('universe', [])
            print(f"Number of spot assets: {len(spot_assets)}")
            print("First few spot assets:", [asset['name'] for asset in spot_assets[:5]])
        except Exception as e:
            print(f"❌ Cannot get spot assets: {str(e)}")
            
        # Check both account states
        print("\n=== ACCOUNT STATE CHECK ===")
        try:
            # Check perp state
            user_state = info.user_state(config.account_address)
            print("\nPerp State:")
            if 'marginSummary' in user_state:
                account_value = float(user_state['marginSummary'].get('accountValue', 0))
                print(f"Account Value: ${account_value:.2f}")
            else:
                print("No margin summary found")
                
            # Check spot state
            spot_state = info.spot_user_state(config.account_address)
            print("\nSpot State:")
            if spot_state.get('balances'):
                for balance in spot_state['balances']:
                    print(f"{balance['coin']}: {float(balance['total']):.8f}")
            else:
                print("No balances found")
                
            print("\nFull spot state for debugging:")
            print(spot_state)
                
        except Exception as e:
            print(f"❌ Cannot get account state: {str(e)}")

    except Exception as e:
        print(f"\n❌ Setup error: {str(e)}")

if __name__ == "__main__":
    check_wallet_connection()