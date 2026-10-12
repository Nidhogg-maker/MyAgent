-- as_of_date is an exclusive UTC cutoff; attributes with unverified history are omitted.
with a as (
  select user_id,
         sum(product_view_count) filter(where activity_date >= date '{{ var("feature_as_of") }}' - 7) as product_views_7d,
         sum(product_view_count) as product_views_30d,
         sum(cart_event_count) as cart_events_30d,
         sum(placed_order_count) as placed_orders_30d,
         sum(placed_item_count) as placed_items_30d,
         sum(booked_amount) as booked_amount_30d
  from {{ ref('dws_user_behavior_day') }}
  where activity_date >= date '{{ var("feature_as_of") }}' - 30
    and activity_date < date '{{ var("feature_as_of") }}'
  group by user_id
), last_order as (
  select user_id,max(last_order_at) as last_order_at
  from {{ ref('dws_user_behavior_day') }} group by user_id
)
select u.id as user_id, date '{{ var("feature_as_of") }}' as as_of_date,
       coalesce(a.product_views_7d,0) as product_views_7d,
       coalesce(a.product_views_30d,0) as product_views_30d,
       coalesce(a.cart_events_30d,0) as cart_events_30d,
       coalesce(a.placed_orders_30d,0) as placed_orders_30d,
       coalesce(a.placed_items_30d,0) as placed_items_30d,
       coalesce(a.booked_amount_30d,0)::decimal(18,4) as booked_amount_30d,
       l.last_order_at,
       date_diff('day',cast(timezone('UTC',l.last_order_at) as date),date '{{ var("feature_as_of") }}') as days_since_last_order,
       'snapshot-observed-history; not production point-in-time certified' as temporal_scope
from {{ source('thelook_features', 'users') }} u
left join a on u.id=a.user_id left join last_order l on u.id=l.user_id
where u.created_at < timestamptz '{{ var("feature_as_of") }} 00:00:00+00'
