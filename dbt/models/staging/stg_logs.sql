select
    block_number,
    timezone('UTC', block_time)                           as block_time,
    cast(timezone('UTC', block_time) as date)            as block_date,
    lower(tx_hash)                                        as tx_hash,
    log_index,
    lower(contract_address)                               as contract_address,
    topic0, topic1, topic2, topic3,
    data
from {{ source('raw', 'raw_logs') }}
