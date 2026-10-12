-- Guard against decimals / decoding bugs: no single swap above $50M, none negative.
select * from {{ ref('int_swaps_decoded') }} where amount_usd < 0 or amount_usd > 5e7
