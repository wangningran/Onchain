select
    lower(contract_address) as token_address,
    symbol,
    decimals,
    is_stable,
    pricing_priority          -- lower = more trustworthy leg for USD pricing (stables first)
from {{ source('raw', 'raw_tokens') }}
