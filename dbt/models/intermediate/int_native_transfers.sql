-- Plain ETH sends (value > 0). The first inbound ETH transfer = a wallet's "funder",
-- the single most useful edge for sybil / wash-trading clustering.
select block_time, block_date, tx_hash, tx_from as from_address, tx_to as to_address, value_eth
from {{ ref('stg_transactions') }}
where success and value_eth > 0
