select 'item_order' as failure, i.id as row_id
from {{ source('thelook','order_items') }} i
left join {{ source('thelook','orders') }} o on i.order_id = o.order_id
where o.order_id is null or i.user_id != o.user_id
union all
select 'item_product', i.id from {{ source('thelook','order_items') }} i
left join {{ ref('dim_products') }} p on i.product_id = p.product_id where p.product_id is null
union all
select 'item_inventory', i.id from {{ source('thelook','order_items') }} i
left join {{ source('thelook','inventory_items') }} v on i.inventory_item_id = v.id
where v.id is null or i.product_id != v.product_id
union all
select 'order_user', o.order_id from {{ source('thelook','orders') }} o
left join {{ ref('dim_users') }} u on o.user_id = u.user_id where u.user_id is null
