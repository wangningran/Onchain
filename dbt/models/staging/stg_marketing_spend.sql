select cast(day as date) as day, channel, spend_usd
from {{ source('raw', 'raw_marketing_spend') }}
