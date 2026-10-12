# EVM data model: what's actually in the tables

## Transaction (`ethereum.transactions`)
| field | meaning | analyst gotcha |
|---|---|---|
| `hash` | tx id | join key to logs/traces (also join on `block_time` for pruning) |
| `from` | EOA that signed & paid gas | **the economic actor** in almost every analysis |
| `to` | contract called (router, aggregator, bot contract, token) or EOA for plain ETH sends | `to` = known router ⇒ front-end / normal user; custom contract ⇒ bot/MEV/aggregator |
| `value` | wei of native ETH sent | `/1e18`; ERC20 movements are NOT here, they're in logs |
| `gas_used × gas_price` | fee paid (wei) | EIP-1559: effective price = base fee + priority tip |
| `success` | receipt status | failed txs still cost gas and have **no logs**: filter them before counting "actions" |
| `nonce` | per-sender counter | nonce 0/low ⇒ fresh wallet (sybil signal) |

## Log / event (`ethereum.logs`)
```
contract_address  = emitter (pool, token, ...)
topic0            = keccak256("EventName(type1,type2,...)")  — identifies the event
topic1..topic3    = up to 3 `indexed` args, each left-padded to 32 bytes
data              = ABI-encoded non-indexed args, 32-byte words, in declaration order
index             = log index within the block (unique key with tx_hash)
```
- Address in a topic: last 20 bytes → Dune `bytearray_substring(topic1, 13, 20)`; hex string: `'0x' || substr(topic, 27, 40)`.
- uint in data word n (0-based): Dune `bytearray_to_uint256(bytearray_substring(data, 1 + 32*n, 32))`.
- Divide by `10^decimals` from `tokens.erc20`: USDC/USDT 6, WBTC 8, most 18.
- **Anyone can emit any event.** Always filter `contract_address` to a vetted set (factory-created pairs), not just `topic0`. Scam tokens emit fake `Transfer`s to spoof activity.
- `hashlib.sha3_256` ≠ Ethereum keccak256 (different padding). Use `scripts/evm_tools.py`.

## Common signatures
| event | topic0 | indexed | data |
|---|---|---|---|
| ERC20 `Transfer(address,address,uint256)` | `0xddf252ad…b3ef` | from, to | value |
| ERC20 `Approval(address,address,uint256)` | `0x8c5be1e5…b925` | owner, spender | value |
| V2 `Swap(address,uint256,uint256,uint256,uint256,address)` | `0xd78ad95f…d822` | sender, to | a0In, a1In, a0Out, a1Out |
| V2 `Sync(uint112,uint112)` | `0x1c411e9a…bad1` | – | reserve0, reserve1 |
| V2 `Mint(address,uint256,uint256)` | `0x4c209b5f…1c4f` | sender | amount0, amount1 |
| V2 `Burn(address,uint256,uint256,address)` | `0xdccd412f…6496` | sender, to | amount0, amount1 |
| V3 `Swap(address,address,int256,int256,uint160,uint128,int24)` | `0xc42079f9…ca67` | sender, recipient | amount0, amount1 (signed: + into pool), sqrtPriceX96, liquidity, tick |

## AMM mechanics you need for metrics
- V2 constant product `x·y = k`; fee 0.30% stays in the pool (LPs), protocol fee optional (1/6 of fee if switched on).
- Pool price token1 in token0 = `reserve0 / reserve1` (after decimals). V3: `price = (sqrtPriceX96 / 2^96)^2 × 10^(dec0−dec1)`.
- `token0` is the lower address. Don't assume WETH is token1.
- TVL (V2) = `reserve0·p0 + reserve1·p1` from the last `Sync` of the period. V3 TVL = token balances of the pool (positions are ranges).
- Impermanent loss (50/50, V2) for price ratio r: `IL = 2√r/(1+r) − 1`. V3 IL is amplified inside the range.
- Arbitrage bots keep pool price ≈ CEX price; much "volume" on majors is arb, not demand.

## Traces / internal txs
Contract-to-contract ETH moves (e.g. WETH unwrap, multisig payouts) only appear in `ethereum.traces`. Funding-cluster analysis on smart wallets needs traces, not just transactions.

## Account abstraction & L2 caveats
- ERC-4337: `tx.from` is the bundler. The user is the `sender` in `UserOperationEvent`. Use `erc4337` spells.
- L2s (Base, Arbitrum, OP): cheap gas means far more bot/sybil volume, so apply the bot screen more aggressively. L1 data fee is a separate component of the fee.
