-- ERC20 Transfer(from indexed, to indexed, value) for tracked tokens (~ Dune tokens.transfers)
select
    l.block_time, l.block_date, l.tx_hash, l.log_index,
    t.token_address, t.symbol,
    {{ topic_to_address('l.topic1') }}                       as from_address,
    {{ topic_to_address('l.topic2') }}                       as to_address,
    {{ hex_word_to_amount('l.data', 0, 't.decimals') }}       as amount
from {{ ref('stg_logs') }} l
join {{ ref('stg_tokens') }} t on t.token_address = l.contract_address
where l.topic0 = '{{ var("topic_transfer") }}'
