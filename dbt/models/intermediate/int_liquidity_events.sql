-- Mint(sender, amount0, amount1) / Burn(sender, amount0, amount1, to). LP = tx_from.
select
    l.block_time, l.block_date, l.tx_hash, l.log_index,
    p.pool_address, p.pool_name,
    case when l.topic0 = '{{ var("topic_mint") }}' then 'add' else 'remove' end as event_type,
    t.tx_from                                                      as provider,
    {{ hex_word_to_amount('l.data', 0, 'p.token0_decimals') }}     as amount0,
    {{ hex_word_to_amount('l.data', 1, 'p.token1_decimals') }}     as amount1,
    {{ hex_word_to_amount('l.data', 0, 'p.token0_decimals') }} * p0.price_usd
      + {{ hex_word_to_amount('l.data', 1, 'p.token1_decimals') }} * p1.price_usd as amount_usd
from {{ ref('stg_logs') }} l
join {{ ref('stg_pools') }} p on p.pool_address = l.contract_address
join {{ ref('stg_transactions') }} t on t.tx_hash = l.tx_hash
left join {{ ref('stg_prices_daily') }} p0 on p0.token_address = p.token0_address and p0.day = l.block_date
left join {{ ref('stg_prices_daily') }} p1 on p1.token_address = p.token1_address and p1.day = l.block_date
where l.topic0 in ('{{ var("topic_mint") }}', '{{ var("topic_burn") }}')
