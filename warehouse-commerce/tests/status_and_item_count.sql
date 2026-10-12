select order_id as row_id, 'declared_item_count' as failure from {{ ref('fct_orders') }}
where declared_item_count != item_count
union all
select order_item_id, 'item_status' from {{ ref('fct_order_items') }}
where item_status is null or item_status not in ('Complete', 'Returned', 'Cancelled', 'Processing', 'Shipped')
