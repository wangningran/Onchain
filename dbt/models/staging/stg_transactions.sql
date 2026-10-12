select
    block_number,
    timezone('UTC', block_time)                           as block_time,
    cast(timezone('UTC', block_time) as date)            as block_date,
    lower(hash)                                           as tx_hash,
    lower(from_address)                                   as tx_from,
    lower(to_address)                                     as tx_to,
    cast(value_wei as hugeint) / 1e18                     as value_eth,
    gas_used,
    gas_price_gwei,
    gas_used * gas_price_gwei / 1e9                       as gas_fee_eth,
    success
from {{ source('raw', 'raw_transactions') }}
