-- User-level (anonymous_id = randomisation unit) outcomes for the swap-UI experiment.
-- Analysing at the session level would violate independence (users have many sessions).
select
    anonymous_id,
    any_value(experiment_variant)                 as variant,
    count(*)                                      as sessions,
    max(quoted)                                   as quoted,
    max(submitted)                                as submitted,
    max(confirmed)                                as confirmed,
    sum(quoted)                                   as quoted_sessions,
    sum(submitted)                                as submitted_sessions,
    count(distinct experiment_variant)            as n_variants_seen   -- must be 1 (assignment sanity)
from {{ ref('int_session_funnel') }}
where experiment_variant is not null
  and session_date between date '{{ var("experiment_start") }}' and date '{{ var("experiment_end") }}'
group by 1
