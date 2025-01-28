# Baby Smith

<div align="center">

![Version](https://img.shields.io/badge/version-1.0.0-blue)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Dependencies Status](https://img.shields.io/badge/dependencies-up%20to%20date-brightgreen.svg)](https://github.com/hydralabs-sh/baby-smith/pulls?utf8=%E2%9C%93&q=is%3Apr%20author%3Aapp%2Fdependabot)

A simplified autonomous trading agent for [Hyperliquid](https://hyperliquid.xyz), derived from Agent Smith.

⚠️ **USE AT YOUR OWN RISK** ⚠️

</div>

## ⚠️ Important Warning

Baby Smith is **experimental software** that can autonomously trade with real money. The consequences of bugs, market events, or other unforeseen circumstances could result in **immediate and total loss of funds**.

By using this software:

- You acknowledge that you are solely responsible for any losses
- You understand that autonomous trading is inherently risky
- You accept that no warranties or guarantees are provided
- You agree to the terms of the MIT license

## Overview

Baby Smith is a simplified autonomous trading agent for Hyperliquid perpetual futures. It includes:

- Basic market making strategy
- Position management
- Rate limiting
- Risk controls
- Real-time monitoring

## Prerequisites

- [Poetry](https://python-poetry.org/docs/#installation) (Python package manager)
- Docker and Docker Compose (optional)
- A funded Hyperliquid account
- Private key with trading permissions
- Basic understanding of perpetual futures trading

## Quick Start

### Using Docker (Recommended)

1. Clone the repository:

```bash
git clone https://github.com/hydralabs-sh/baby-smith.git
cd baby-smith
```

2. Copy and configure environment variables:

```bash
cp .env.template .env
```

3. Edit `.env` with your credentials:

```
# Required - Trading Account
HL_ACCOUNT_ADDRESS=your_account_address
HL_SECRET_KEY=your_private_key

# Optional - Trading Parameters
HL_ASSET=HYPE
HL_MAX_POSITION=5.0
HL_BASE_POSITION=1.0
HL_LEVERAGE=3
HL_TESTNET=true
```

4. Start the agent:

```bash
docker compose up
```

### Using Poetry (Development)

1. Clone and enter the repository:

```bash
git clone https://github.com/hydralabs-sh/baby-smith.git
cd baby-smith
```

2. Install dependencies using Poetry:

```bash
poetry install
```

3. Copy and configure environment variables:

```bash
cp .env.template .env
# Edit .env with your settings
```

4. Run the agent:

```bash
poetry run python -m agent_smith.main
```

## Configuration Parameters

| Parameter          | Description                                     | Default |
| ------------------ | ----------------------------------------------- | ------- |
| HL_ACCOUNT_ADDRESS | Your Hyperliquid account address (required)     | None    |
| HL_SECRET_KEY      | Private key with trading permissions (required) | None    |
| HL_ASSET           | Trading asset                                   | HYPE    |
| HL_MAX_POSITION    | Maximum position size                           | 5.0     |
| HL_BASE_POSITION   | Target position size                            | 1.0     |
| HL_LEVERAGE        | Trading leverage                                | 3       |
| HL_TESTNET         | Use testnet instead of mainnet                  | true    |

## Architecture

Baby Smith consists of several key components:

- `agent.py` - Main trading logic and order execution
- `strategies/` - Trading strategy implementations
- `metrics.py` - Performance tracking
- `rate_limit.py` - Request rate management
- `dashboard.py` - Real-time monitoring interface

## Monitoring

The agent provides a real-time dashboard at `http://localhost:8501` showing:

- Current positions
- Account value
- Recent trades
- PnL metrics
- Market data

## Risk Controls

Built-in risk management features:

- Maximum position limits
- Rate limiting
- Slippage protection
- Position reduction logic
- Price deviation checks

## Development

The project uses Poetry for dependency management. To set up a development environment:

1. Install Poetry if you haven't already:

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. Install dependencies:

```bash
poetry install
```

3. Activate the virtual environment:

```bash
poetry shell
```

4. Run tests:

```bash
poetry run pytest
```

5. Run the agent:

```bash
poetry run python -m agent_smith.main
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Install development dependencies: `poetry install --with dev`
4. Run tests: `poetry run pytest`
5. Commit your changes
6. Push to the branch
7. Create a Pull Request

## Project Dependencies

This project uses Poetry for dependency management. Key dependencies include:

- hyperliquid-python-sdk
- streamlit (for dashboard)
- pandas (for data processing)
- loguru (for logging)
- pydantic (for config)

To add new dependencies:

```bash
poetry add package_name
```

For development dependencies:

```bash
poetry add --group dev package_name
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE.md) file for details.

## Disclaimer

THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

The developers of Baby Smith take no responsibility and assume no liability for any money lost through the use of this software. Use at your own risk.

## Support

For questions and support:

- Visit the [Hyperliquid Documentation](https://hyperliquid.xyz/docs)

---

**Remember:** This is experimental software for educational purposes. Never trade with more money than you can afford to lose.

© Copyright 2025 HYDRA Labs - MIT License
