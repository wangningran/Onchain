-- Acquisition efficiency per channel x first-swap month: CAC, D30 retention and a 30-day
-- fee-based LTV proxy. Only cohorts with a complete 30-day window count toward retention/LTV.
with users as (
    select wallet, acquisition_channel as channel, first_swap_date,
           date_trunc('month', first_swap_date) as cohort_month
    from {{ ref('dim_wallets') }}
    where wallet_type = 'user' and acquisition_channel is not null
),
horizon as (select max(block_date) as max_day from {{ ref('fct_swaps') }}),
d30 as (
    select u.wallet,
           max(case when s.block_date > u.first_swap_date
                     and s.block_date <= u.first_swap_date + interval 30 day then 1 else 0 end) as retained_d30,
           sum(case when s.block_date <= u.first_swap_date + interval 30 day then s.amount_usd else 0 end) as volume_30d,
           sum(case when s.block_date <= u.first_swap_date + interval 30 day then s.lp_fee_usd else 0 end) as fees_30d
    from users u
    join {{ ref('fct_swaps') }} s on s.trader = u.wallet
    group by 1
),
spend as (
    select channel, date_trunc('month', day) as cohort_month, sum(spend_usd) as spend_usd
    from {{ ref('stg_marketing_spend') }}
    group by 1, 2
)
select
    u.channel,
    u.cohort_month,
    count(*)                                                    as new_traders,
    coalesce(max(sp.spend_usd), 0)                              as spend_usd,
    coalesce(max(sp.spend_usd), 0) / count(*)                   as cac_usd,
    avg(case when u.first_swap_date + interval 30 day <= h.max_day then d.retained_d30 end) as d30_retention,
    avg(case when u.first_swap_date + interval 30 day <= h.max_day then d.volume_30d end)   as avg_volume_30d,
    avg(case when u.first_swap_date + interval 30 day <= h.max_day then d.fees_30d end)     as ltv_30d_fees_usd
from users u
cross join horizon h
join d30 d using (wallet)
left join spend sp on sp.channel = u.channel and sp.cohort_month = u.cohort_month
group by 1, 2
order by 1, 2
