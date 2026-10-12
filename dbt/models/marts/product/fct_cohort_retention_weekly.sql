with users as (
    select wallet, date_trunc('week', first_swap_date) as cohort_week, acquisition_channel
    from {{ ref('dim_wallets') }}
    where wallet_type = 'user'
),
activity as (
    select distinct trader as wallet, date_trunc('week', block_date) as activity_week
    from {{ ref('fct_swaps') }}
    where is_user
),
sizes as (select cohort_week, count(*) as cohort_size from users group by 1)
select
    u.cohort_week,
    datediff('week', u.cohort_week, a.activity_week)   as weeks_since_first,
    count(distinct a.wallet)                           as active_wallets,
    s.cohort_size,
    count(distinct a.wallet) / s.cohort_size           as retention_rate
from users u
join activity a using (wallet)
join sizes s using (cohort_week)
group by u.cohort_week, weeks_since_first, s.cohort_size
order by 1, 2
