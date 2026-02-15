# SilkyWay -- Agent Banking for Sandstorm

SilkyWay is the bank for AI agents. Agents open accounts, earn yield on idle USDC balances (4.5-8% APY), and transact under policy controls set by their owners. Non-custodial, no KYC, instant liquidity.

## What this example does

This `sandstorm.json` configures a Sandstorm agent with the SilkyWay MCP server, giving it access to on-chain banking tools. The agent can:

- **Open accounts** -- create new USDC accounts on Solana
- **Deposit and withdraw** -- move funds in and out
- **Earn yield** -- idle balances are automatically routed to yield strategies
- **Make payments** -- send USDC to other agents or wallets
- **Check balances** -- query account state and transaction history

## Usage

Copy `sandstorm.json` to your Sandstorm project root (or merge the `mcp_servers` block into your existing config), then query:

```bash
curl -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Open a SilkyWay account, deposit 1000 USDC, and confirm my balance"}'
```

## Links

- [SilkyWay](https://silkyway.app)
- [Sandstorm docs](https://github.com/tomascupr/sandstorm)
- [MCP protocol](https://modelcontextprotocol.io)
