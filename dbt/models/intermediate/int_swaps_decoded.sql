-- Decode Uniswap-V2 style Swap(sender, amount0In, amount1In, amount0Out, amount1Out, to) logs.
-- Key points (same on Dune):
--   * filter by topic0 AND by known pool addresses, otherwise any contract emitting the same
--     signature (forks, scam pairs) pollutes the data
--   * the economic trader is tx_from (EOA), not topic1 `sender` (router / bot contract)
--   * USD value is taken from the most trustworthy leg (stables > WETH > long-tail token)
with swaps as (
    select
        l.block_time, l.block_date, l.block_number, l.tx_hash, l.log_index,
        p.pool_address, p.pool_name, p.fee_bps,
        p.token0_address, p.token0_symbol, p.token1_address, p.token1_symbol,
        {{ topic_to_address('l.topic1') }}                                     as swap_sender,
        {{ topic_to_address('l.topic2') }}                                     as swap_recipient,
        {{ hex_word_to_amount('l.data', 0, 'p.token0_decimals') }}            as amount0_in,
        {{ hex_word_to_amount('l.data', 1, 'p.token1_decimals') }}            as amount1_in,
        {{ hex_word_to_amount('l.data', 2, 'p.token0_decimals') }}            as amount0_out,
        {{ hex_word_to_amount('l.data', 3, 'p.token1_decimals') }}            as amount1_out
    from {{ ref('stg_logs') }} l
    join {{ ref('stg_pools') }} p on p.pool_address = l.contract_address
    where l.topic0 = '{{ var("topic_swap") }}'
),

legs as (
    select
        *,
        case when amount0_in - amount0_out > 0 then token0_address else token1_address end as token_sold_address,
        case when amount0_in - amount0_out > 0 then token0_symbol  else token1_symbol  end as token_sold_symbol,
        case when amount0_in - amount0_out > 0 then token1_address else token0_address end as token_bought_address,
        case when amount0_in - amount0_out > 0 then token1_symbol  else token0_symbol  end as token_bought_symbol,
        abs(amount0_in - amount0_out) as net0,
        abs(amount1_in - amount1_out) as net1
    from swaps
)

select
    s.block_time, s.block_date, s.block_number, s.tx_hash, s.log_index,
    s.pool_address, s.pool_name, s.fee_bps,
    t.tx_from                                         as trader,
    t.tx_to,
    s.swap_sender,
    s.swap_recipient,
    s.token_sold_symbol, s.token_bought_symbol,
    s.token_sold_address, s.token_bought_address,
    case when s.token_sold_address = s.token0_address then s.net0 else s.net1 end   as amount_sold,
    case when s.token_bought_address = s.token0_address then s.net0 else s.net1 end as amount_bought,
    case when ts.pricing_priority <= tb.pricing_priority
         then (case when s.token_sold_address = s.token0_address then s.net0 else s.net1 end) * ps.price_usd
         else (case when s.token_bought_address = s.token0_address then s.net0 else s.net1 end) * pb.price_usd
    end                                               as amount_usd,
    t.gas_fee_eth
from legs s
join {{ ref('stg_transactions') }} t on t.tx_hash = s.tx_hash
join {{ ref('stg_tokens') }} ts on ts.token_address = s.token_sold_address
join {{ ref('stg_tokens') }} tb on tb.token_address = s.token_bought_address
left join {{ ref('stg_prices_daily') }} ps on ps.token_address = s.token_sold_address  and ps.day = s.block_date
left join {{ ref('stg_prices_daily') }} pb on pb.token_address = s.token_bought_address and pb.day = s.block_date
where t.success
