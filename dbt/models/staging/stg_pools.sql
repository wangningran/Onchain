select
    lower(p.pool_address)  as pool_address,
    p.pool_name,
    p.fee_bps,
    t0.token_address       as token0_address,
    t0.symbol              as token0_symbol,
    t0.decimals            as token0_decimals,
    t1.token_address       as token1_address,
    t1.symbol              as token1_symbol,
    t1.decimals            as token1_decimals
from {{ source('raw', 'raw_pools') }} p
join {{ ref('stg_tokens') }} t0 on t0.token_address = lower(p.token0_address)
join {{ ref('stg_tokens') }} t1 on t1.token_address = lower(p.token1_address)
