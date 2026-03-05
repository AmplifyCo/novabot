# Wallet Tool — Usage Guidelines

## Security (CRITICAL)
- NEVER expose private keys, seed phrases, or keystore contents in responses
- NEVER log or display private keys — only show public addresses
- When reporting balances, always show both native token (ETH/SOL) and USDC

## Spending Rules
- All sends require the two-step approval flow: send → approval code → confirm_send
- Approval codes expire after 5 minutes
- Respect spending limits: per-transaction and daily maximums
- Transfers to the owner's personal wallet bypass spending limits (sweep)

## Auto-Sweep
- When USDC balance exceeds the sweep threshold, notify the owner and offer to sweep
- Sweep keeps a small buffer for gas/fees — never sweep everything
- Always confirm sweep amount before executing

## When to Use
- "Check my wallet" / "How much USDC do I have?" → balance operation
- "What's my address?" → address operation
- "Send X USDC to [address]" → send operation (requires confirmation)
- "Show recent transactions" → ledger operation

## Communication
- Report balances in plain language: "You have 150 USDC and 0.01 ETH on Base"
- For transactions, always report the tx hash and a confirmation
- If a transaction fails, explain why clearly (insufficient funds, gas issues, etc.)
