-- Each funnel step must be a subset of the previous one.
select *
from {{ ref('fct_funnel_daily') }}
where connected > sessions or quoted > connected or submitted > quoted or confirmed > submitted
