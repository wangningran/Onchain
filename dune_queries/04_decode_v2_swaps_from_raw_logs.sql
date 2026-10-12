-- Decode Uniswap-V2-style Swap events straight from ethereum.logs, then reconcile with dex.trades.
-- Use this pattern for any protocol Dune hasn't decoded / spelled yet.  Param: {{pair}} (0x... pair address)
WITH pair AS (
    SELECT token0, token1 FROM uniswap_v2_ethereum.Factory_evt_PairCreated WHERE pair = {{pair}}
),
raw AS (
    SELECT
        l.block_time,
        l.tx_hash,
        l.index                                                            AS log_index,
        bytearray_substring(l.topic1, 13, 20)                              AS sender,      -- router / aggregator
        bytearray_substring(l.topic2, 13, 20)                              AS recipient,
        bytearray_to_uint256(bytearray_substring(l.data,  1, 32))          AS amount0_in,
        bytearray_to_uint256(bytearray_substring(l.data, 33, 32))          AS amount1_in,
        bytearray_to_uint256(bytearray_substring(l.data, 65, 32))          AS amount0_out,
        bytearray_to_uint256(bytearray_substring(l.data, 97, 32))          AS amount1_out
    FROM ethereum.logs l
    WHERE l.contract_address = {{pair}}
      AND l.topic0 = 0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822  -- Swap(address,uint256,uint256,uint256,uint256,address)
      AND l.block_time >= NOW() - INTERVAL '7' DAY
)
SELECT
    r.block_time, r.tx_hash, r.log_index, t."from" AS trader, r.sender,
    (CAST(r.amount0_in AS DOUBLE) - CAST(r.amount0_out AS DOUBLE)) / POWER(10, t0.decimals) AS token0_net_in,
    (CAST(r.amount1_in AS DOUBLE) - CAST(r.amount1_out AS DOUBLE)) / POWER(10, t1.decimals) AS token1_net_in,
    t0.symbol AS token0_symbol, t1.symbol AS token1_symbol,
    d.amount_usd                                                           AS spell_amount_usd   -- reconciliation: NULL => our decode found a trade the spell lacks
FROM raw r
CROSS JOIN pair p
JOIN ethereum.transactions t ON t.hash = r.tx_hash AND t.block_time = r.block_time   -- join on block_time too: partition pruning
JOIN tokens.erc20 t0 ON t0.contract_address = p.token0 AND t0.blockchain = 'ethereum'
JOIN tokens.erc20 t1 ON t1.contract_address = p.token1 AND t1.blockchain = 'ethereum'
LEFT JOIN dex.trades d ON d.blockchain = 'ethereum' AND d.tx_hash = r.tx_hash AND d.evt_index = r.log_index
     AND d.block_time >= NOW() - INTERVAL '7' DAY
ORDER BY r.block_time DESC
