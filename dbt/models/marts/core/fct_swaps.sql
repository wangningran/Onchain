select
    s.*,
    w.wallet_type,
    w.wallet_type = 'user'                                  as is_user,
    s.amount_usd * s.fee_bps / 1e4                          as lp_fee_usd,
    cast(s.block_time as date) = w.first_swap_date          as is_first_swap_day
from {{ ref('int_swaps_decoded') }} s
left join {{ ref('dim_wallets') }} w on w.wallet = s.trader
