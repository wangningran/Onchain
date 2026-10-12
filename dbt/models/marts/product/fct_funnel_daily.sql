select
    session_date                                  as day,
    coalesce(experiment_variant, 'none')          as experiment_variant,
    is_returning,
    channel,
    count(*)                                      as sessions,
    sum(connected)                                as connected,
    sum(quoted)                                   as quoted,
    sum(submitted)                                as submitted,
    sum(confirmed)                                as confirmed
from {{ ref('int_session_funnel') }}
group by all
