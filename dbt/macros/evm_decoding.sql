{#
  EVM log decoding helpers for DuckDB.

  On Dune (Trino) the equivalents are native:
    bytearray_to_uint256(bytearray_substring(data, 1 + 32*n, 32))
    bytearray_ltrim(topic1)  /  varbinary_substring(topic1, 13, 20)
  Here `data` / `topicN` are 0x-prefixed hex strings, so we slice characters instead of bytes.
#}

{# n-th 32-byte ABI word of `data` (0-based) as UHUGEINT. Uses the low 128 bits, which covers
   every realistic token amount (< 3.4e38 base units). #}
{% macro hex_word_to_uint(data_col, n) -%}
  (
    (('0x' || substr({{ data_col }}, {{ 3 + 64 * n + 32 }}, 16))::UBIGINT)::UHUGEINT * 18446744073709551616::UHUGEINT
    + (('0x' || substr({{ data_col }}, {{ 3 + 64 * n + 48 }}, 16))::UBIGINT)::UHUGEINT
  )
{%- endmacro %}

{# Same as above, scaled by token decimals -> DOUBLE token units #}
{% macro hex_word_to_amount(data_col, n, decimals_col) -%}
  ({{ hex_word_to_uint(data_col, n) }}::DOUBLE / pow(10, {{ decimals_col }}))
{%- endmacro %}

{# Indexed address topics are left-padded to 32 bytes: keep the last 20 bytes #}
{% macro topic_to_address(topic_col) -%}
  ('0x' || substr({{ topic_col }}, 27, 40))
{%- endmacro %}
