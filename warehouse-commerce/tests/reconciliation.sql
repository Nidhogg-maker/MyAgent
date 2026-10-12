-- Independent raw total checks, including losses from missing dimension/parent joins.
select 'item_count' as failure
where (select count(*) from {{ ref('fct_order_items') }}) != (select count(*) from {{ source('thelook','order_items') }})
union all
select 'order_count' where (select count(*) from {{ ref('fct_orders') }}) != (select count(*) from {{ source('thelook','orders') }})
union all
select 'booked_amount' where
  (select sum(booked_item_amount) from {{ ref('fct_order_items') }}) !=
  (select sum(cast(sale_price as decimal(18,4))) from {{ source('thelook','order_items') }})
union all
select 'order_vs_item_amount' where
  (select sum(booked_order_amount) from {{ ref('fct_orders') }}) !=
  (select sum(booked_item_amount) from {{ ref('fct_order_items') }})
union all
select 'dws_amount' where (select sum(booked_item_amount) from {{ ref('dws_daily_sales') }}) !=
  (select sum(booked_item_amount) from {{ ref('fct_order_items') }})
