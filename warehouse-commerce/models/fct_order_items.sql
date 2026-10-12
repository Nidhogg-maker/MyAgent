-- One row per order_item_id. All joins here target unique keys, never events/session rows.
select i.id as order_item_id, i.order_id, i.user_id, i.product_id, i.inventory_item_id,
       i.status as item_status, o.status as order_status,
       o.created_at as order_created_at,
       cast(timezone('UTC', o.created_at) as date) as order_date,
       i.created_at as item_created_at, i.shipped_at, i.delivered_at, i.returned_at,
       cast(i.sale_price as decimal(18,4)) as booked_item_amount,
       cast(v.cost as decimal(18,4)) as inventory_item_cost,
       case when i.status = 'Complete' then 1 else 0 end as complete_item,
       case when i.status = 'Returned' then 1 else 0 end as returned_item,
       case when i.status = 'Cancelled' then 1 else 0 end as cancelled_item,
       u.country, u.gender, u.age_band, u.traffic_source,
       p.category, p.brand, p.department, p.distribution_center_id
from {{ source('thelook', 'order_items') }} i
join {{ source('thelook', 'orders') }} o on i.order_id = o.order_id
left join {{ source('thelook', 'inventory_items') }} v on i.inventory_item_id = v.id
left join {{ ref('dim_users') }} u on i.user_id = u.user_id
left join {{ ref('dim_products') }} p on i.product_id = p.product_id
