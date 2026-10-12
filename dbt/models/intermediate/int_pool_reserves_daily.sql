-- TVL from Sync(reserve0, reserve1): end-of-day reserves, forward-filled across days with no
-- activity, valued at that day's prices. This is how you'd compute TVL on Dune when no
-- curated "tvl" spell exists (and a good cross-check against DefiLlama).
with syncs as (
    select
        l.contract_address as pool_address,
        l.block_date,
        {{ hex_word_to_amount('l.data', 0, 'p.token0_decimals') }} as reserve0,
        {{ hex_word_to_amount('l.data', 1, 'p.token1_decimals') }} as reserve1,
        row_number() over (partition by l.contract_address, l.block_date
                           order by l.block_number desc, l.log_index desc) as rn
    from {{ ref('stg_logs') }} l
    join {{ ref('stg_pools') }} p on p.pool_address = l.contract_address
    where l.topic0 = '{{ var("topic_sync") }}'
),
eod as (select pool_address, block_date, reserve0, reserve1 from syncs where rn = 1),
spine as (
    select p.pool_address, d.day
    from {{ ref('stg_pools') }} p
    cross join (select distinct day from {{ ref('stg_prices_daily') }}
                where day <= (select max(block_date) from {{ ref('stg_logs') }})) d
),
filled as (
    select
        s.pool_address, s.day,
        last_value(e.reserve0 ignore nulls) over w as reserve0,
        last_value(e.reserve1 ignore nulls) over w as reserve1
    from spine s
    left join eod e on e.pool_address = s.pool_address and e.block_date = s.day
    window w as (partition by s.pool_address order by s.day rows between unbounded preceding and current row)
)
select
    f.pool_address, p.pool_name, f.day,
    f.reserve0, f.reserve1,
    f.reserve0 * p0.price_usd + f.reserve1 * p1.price_usd as tvl_usd
from filled f
join {{ ref('stg_pools') }} p on p.pool_address = f.pool_address
join {{ ref('stg_prices_daily') }} p0 on p0.token_address = p.token0_address and p0.day = f.day
join {{ ref('stg_prices_daily') }} p1 on p1.token_address = p.token1_address and p1.day = f.day
where f.reserve0 is not null
