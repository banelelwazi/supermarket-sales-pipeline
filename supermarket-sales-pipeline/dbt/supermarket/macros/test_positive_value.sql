{#
  Generic test: fails for any row where the column is negative (or zero,
  unless allow_zero is true).
#}
{% test positive_value(model, column_name, allow_zero=false) %}
select {{ column_name }}
from {{ model }}
where {{ column_name }} {{ '<' if allow_zero else '<=' }} 0
{% endtest %}
