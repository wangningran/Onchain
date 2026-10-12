select
    cast(p.day as date) as day,
    t.token_address,
    p.symbol,
    p.price_usd
from {{ source('raw', 'raw_prices_daily') }} p
join {{ ref('stg_tokens') }} t using (symbol)
