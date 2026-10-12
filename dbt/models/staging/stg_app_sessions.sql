select
    session_id,
    anonymous_id,
    timezone('UTC', session_start)                 as session_start,
    cast(timezone('UTC', session_start) as date)  as session_date,
    channel,
    utm_campaign,
    experiment_variant,
    is_returning
from {{ source('raw', 'raw_app_sessions') }}
