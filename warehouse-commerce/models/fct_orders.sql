-- Aggregate item branches first, then attach to order grain to prevent fanout.
with item_totals as (
  select order_id, count(*) as item_count, sum(booked_item_amount) as booked_order_amount,
         sum(case when complete_item = 1 then booked_item_amount else 0 end) as complete_item_amount,
         sum(case when returned_item = 1 then booked_item_amount else 0 end) as returned_item_amount,
         sum(inventory_item_cost) as inventory_cost
  from {{ ref('fct_order_items') }} group by order_id
)
select o.order_id, o.user_id, o.status as order_status, o.created_at,
       cast(timezone('UTC', o.created_at) as date) as order_date,
       o.shipped_at, o.delivered_at, o.returned_at, o.num_of_item as declared_item_count,
       coalesce(i.item_count, 0) as item_count, i.booked_order_amount,
       i.complete_item_amount, i.returned_item_amount, i.inventory_cost,
       u.country, u.gender, u.age_band, u.traffic_source
from {{ source('thelook', 'orders') }} o
left join item_totals i on o.order_id = i.order_id
left join {{ ref('dim_users') }} u on o.user_id = u.user_id
