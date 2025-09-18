# Environment Setup Guide

## 🔧 Configuration Setup

### 1. Environment Variables

Copy the template file and configure your settings:

```bash
cp .env.template .env
```

Then edit `.env` with your actual values:

```bash
nano .env  # or use your preferred editor
```

### 2. Required Configuration

**⚠️ CRITICAL: Update these values before running:**

```env
# Your actual Hyperliquid wallet credentials
HL_ACCOUNT_ADDRESS=0xYOUR_ACTUAL_WALLET_ADDRESS
HL_SECRET_KEY=your_actual_private_key_without_0x

# Network selection
HL_TESTNET="false"  # false for mainnet, true for testnet
HL_EXCHANGE_URL="https://api.hyperliquid.xyz"  # mainnet URL
```

### 3. Security Best Practices

- ✅ **Use a dedicated trading wallet** with limited funds
- ✅ **Never share your private key**
- ✅ **The `.env` file is git-ignored** and won't be committed
- ✅ **Start with small position sizes** for testing

### 4. Configuration Options

#### Network Settings
- `HL_TESTNET="true"` - Use testnet for testing
- `HL_TESTNET="false"` - Use mainnet for live trading

#### Trading Parameters
- `HL_ASSET="ETH"` - Asset to trade
- `HL_MAX_POSITION="1.0"` - Maximum position size
- `HL_MIN_SPREAD="0.001"` - Minimum spread (0.1%)

#### Risk Management
- `HL_MAX_DAILY_LOSS="100"` - Stop trading if daily loss exceeds this
- `HL_ENABLE_TRADING="true"` - Set to false for dry-run mode

## 🚀 Running the Agent

### Docker (Recommended)
```bash
# Build and start
docker compose up agent-baby-smith -d

# Monitor logs
docker compose logs agent-baby-smith -f

# Stop
docker compose stop agent-baby-smith
```

### Direct Python
```bash
# Install dependencies
pip install -r requirements.txt
pip install -e .

# Run
python -m agent_smith.main
```

## 📊 Monitoring

### Real-time Logs
```bash
docker compose logs agent-baby-smith -f
```

### Dashboard (Optional)
```bash
streamlit run src/agent_smith/dashboard.py
```

## 🔒 Security Notes

- The `.env` file contains sensitive credentials and is **automatically ignored by git**
- Never commit real credentials to version control
- Use environment variables in production deployments
- Consider using a secrets management system for production

## 🛠 Troubleshooting

### Common Issues

1. **"Missing environment variables"**
   - Ensure `.env` file exists and contains all required variables

2. **"Connection failed"**
   - Verify network settings (testnet vs mainnet)
   - Check wallet address format (should start with 0x)

3. **"Account value: $0.00"**
   - Fund your wallet with USDC to start trading
   - Ensure you're on the correct network (testnet vs mainnet)