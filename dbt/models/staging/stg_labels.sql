select lower(address) as address, label
from {{ source('raw', 'raw_labels') }}
