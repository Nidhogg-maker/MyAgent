-- Aggregate both branches before combining: never join event detail to item detail.
with events as (
  select event_date as activity_date, user_id,
         count(*) as event_count,
         count(*) filter(where event_type='product' and not invalid_product_reference) as product_view_count,
         count(*) filter(where event_type='cart') as cart_event_count,
         count(*) filter(where event_type='purchase') as purchase_event_count,
         max(event_time_utc) as last_event_at
  from {{ ref('dwd_behavior_event') }}
  where eligible_before_cutoff and user_id is not null and not unknown_user
  group by 1,2
), orders as (
  select order_date as activity_date, user_id, count(distinct order_id) as placed_order_count,
         count(*) as placed_item_count, sum(booked_item_amount) as booked_amount,
         max(order_time_utc) as last_order_at
  from {{ ref('dwd_order_item') }}
  where eligible_before_cutoff and not missing_order and not unknown_user
    and not unknown_product and not user_mismatch and not invalid_amount
  group by 1,2
)
select coalesce(e.activity_date,o.activity_date) as activity_date,
       coalesce(e.user_id,o.user_id) as user_id,
       coalesce(e.event_count,0) as event_count,
       coalesce(e.product_view_count,0) as product_view_count,
       coalesce(e.cart_event_count,0) as cart_event_count,
       coalesce(e.purchase_event_count,0) as purchase_event_count,
       coalesce(o.placed_order_count,0) as placed_order_count,
       coalesce(o.placed_item_count,0) as placed_item_count,
       coalesce(o.booked_amount,0)::decimal(18,4) as booked_amount,
       e.last_event_at, o.last_order_at
from events e full outer join orders o using(activity_date,user_id)
