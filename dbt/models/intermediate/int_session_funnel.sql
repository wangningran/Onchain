-- One row per front-end session with funnel step flags. `confirmed` joins the off-chain
-- swap_submitted event to the on-chain tx receipt (success) via tx_hash: the on/off-chain bridge.
with ev as (
    select
        session_id,
        max(case when event_name = 'wallet_connected' then 1 else 0 end) as connected,
        max(case when event_name = 'quote_requested'  then 1 else 0 end) as quoted,
        max(case when event_name = 'swap_submitted'   then 1 else 0 end) as submitted,
        max(wallet_address)                                               as wallet_address,
        sum(case when event_name = 'quote_requested' then quote_usd end)  as quoted_usd
    from {{ ref('stg_app_events') }}
    group by 1
),
confirmed as (
    select distinct e.session_id
    from {{ ref('stg_app_events') }} e
    join {{ ref('stg_transactions') }} t on t.tx_hash = e.tx_hash and t.success
    where e.event_name = 'swap_submitted'
)
select
    s.session_id, s.anonymous_id, s.session_start, s.session_date, s.channel, s.utm_campaign,
    s.experiment_variant, s.is_returning,
    ev.wallet_address,
    coalesce(ev.connected, 0)                                     as connected,
    coalesce(ev.quoted, 0)                                        as quoted,
    coalesce(ev.submitted, 0)                                     as submitted,
    case when c.session_id is not null then 1 else 0 end          as confirmed,
    ev.quoted_usd
from {{ ref('stg_app_sessions') }} s
left join ev using (session_id)
left join confirmed c using (session_id)
