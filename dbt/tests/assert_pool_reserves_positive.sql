select * from {{ ref('int_pool_reserves_daily') }}
where reserve0 <= 0 or reserve1 <= 0
