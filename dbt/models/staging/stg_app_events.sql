select
    session_id,
    timezone('UTC', event_time) as event_time,
    event_name,
    lower(wallet_address)       as wallet_address,
    lower(tx_hash)              as tx_hash,
    quote_usd
from {{ source('raw', 'raw_app_events') }}
