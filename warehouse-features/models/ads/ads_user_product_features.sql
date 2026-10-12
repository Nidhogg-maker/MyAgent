-- Only historically observed logged-in interactions, not a user-product Cartesian set.
with keys as (
 select user_id,product_id,max(last_view_at) last_view_at,max(last_order_at) last_order_at
 from {{ ref('dws_user_product_day') }} group by 1,2
), recent as (
 select user_id,product_id,
        sum(product_view_count) filter(where activity_date >= date '{{ var("feature_as_of") }}'-7) as product_views_7d,
        sum(product_view_count) as product_views_30d,
        sum(placed_item_count) as placed_items_30d,
        sum(placed_order_count) as placed_orders_30d,sum(booked_amount) as booked_amount_30d
 from {{ ref('dws_user_product_day') }}
 where activity_date >= date '{{ var("feature_as_of") }}'-30
   and activity_date < date '{{ var("feature_as_of") }}' group by 1,2
)
select k.user_id,k.product_id,date '{{ var("feature_as_of") }}' as as_of_date,
       coalesce(r.product_views_7d,0) as product_views_7d,
       coalesce(r.product_views_30d,0) as product_views_30d,
       coalesce(r.placed_items_30d,0) as placed_items_30d,
       coalesce(r.placed_orders_30d,0) as placed_orders_30d,
       coalesce(r.booked_amount_30d,0)::decimal(18,4) as booked_amount_30d,
       k.last_view_at,k.last_order_at,
       greatest(k.last_view_at,k.last_order_at) as last_interaction_at,
       date_diff('day',cast(timezone('UTC',greatest(k.last_view_at,k.last_order_at)) as date),
                 date '{{ var("feature_as_of") }}') as days_since_last_interaction,
       'observed-interaction pairs only; absence is not a negative label' as population_scope
from keys k left join recent r using(user_id,product_id)
