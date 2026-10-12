-- One row per wallet that ever swapped or provided liquidity: behaviour, wallet type,
-- first-touch acquisition channel (off-chain) and on-chain funder (for clustering).
with router as (select address from {{ ref('stg_labels') }} where label = 'router'),
swap_stats as (
    select
        trader                                          as wallet,
        min(block_time)                                 as first_swap_at,
        max(block_time)                                 as last_swap_at,
        count(*)                                        as n_swaps,
        count(distinct block_date)                      as n_active_days,
        count(distinct pool_address)                    as n_pools,
        sum(amount_usd)                                 as volume_usd,
        median(amount_usd)                              as median_swap_usd,
        avg(case when tx_to in (select address from router) then 1.0 else 0.0 end) as router_share
    from {{ ref('int_swaps_decoded') }}
    group by 1
),
lp_stats as (
    select
        provider as wallet,
        sum(case when event_type = 'add' then amount_usd else 0 end)    as lp_added_usd,
        sum(case when event_type = 'remove' then amount_usd else 0 end) as lp_removed_usd,
        min(block_time) as first_lp_at
    from {{ ref('int_liquidity_events') }}
    group by 1
),
first_touch as (
    -- earliest session of any anonymous_id that connected this wallet
    select wallet_address as wallet, arg_min(s.channel, s.session_start) as acquisition_channel
    from {{ ref('int_session_funnel') }} f
    join {{ ref('stg_app_sessions') }} s
      on s.anonymous_id = f.anonymous_id
    where f.wallet_address is not null
    group by 1
),
funder as (
    select to_address as wallet,
           arg_min(from_address, block_time) as funder,
           min(block_time)                   as funded_at
    from {{ ref('int_native_transfers') }}
    group by 1
),
wallets as (
    select wallet from swap_stats union select wallet from lp_stats
)
select
    w.wallet,
    s.first_swap_at,
    cast(s.first_swap_at as date)                              as first_swap_date,
    s.last_swap_at,
    coalesce(s.n_swaps, 0)                                     as n_swaps,
    coalesce(s.n_active_days, 0)                               as n_active_days,
    s.n_pools,
    coalesce(s.volume_usd, 0)                                  as volume_usd,
    s.median_swap_usd,
    coalesce(l.lp_added_usd, 0)                                as lp_added_usd,
    coalesce(l.lp_removed_usd, 0)                              as lp_removed_usd,
    ft.acquisition_channel,
    ft.wallet is not null                                      as has_web_session,
    f.funder,
    f.funded_at,
    lb.label,
    case
        when lb.label in ('mev_bot', 'mev_bot_contract')             then 'mev_bot'
        when lb.label is not null                                      then 'protocol'
        when s.router_share < 0.5                                      then 'contract_caller'
        when coalesce(l.lp_added_usd, 0) > 0 and coalesce(s.n_swaps,0) = 0 then 'lp_only'
        else 'user'
    end                                                        as wallet_type
from wallets w
left join swap_stats s using (wallet)
left join lp_stats l using (wallet)
left join first_touch ft using (wallet)
left join funder f using (wallet)
left join {{ ref('stg_labels') }} lb on lb.address = w.wallet
