-- Current catalog defines the candidate universe; historical availability is unknown.
with a as (
  select product_id,
         sum(product_view_count) filter(where activity_date >= date '{{ var("feature_as_of") }}' - 7) as product_views_7d,
         sum(product_view_count) as product_views_30d,
         sum(anonymous_view_count) as anonymous_views_30d,
         sum(placed_item_count) as placed_items_30d,
         sum(booked_amount) as booked_amount_30d
  from {{ ref('dws_product_behavior_day') }}
  where activity_date >= date '{{ var("feature_as_of") }}' - 30
    and activity_date < date '{{ var("feature_as_of") }}'
  group by product_id
)
select p.id as product_id, date '{{ var("feature_as_of") }}' as as_of_date,
       coalesce(a.product_views_7d,0) as product_views_7d,
       coalesce(a.product_views_30d,0) as product_views_30d,
       coalesce(a.anonymous_views_30d,0) as anonymous_views_30d,
       coalesce(a.placed_items_30d,0) as placed_items_30d,
       coalesce(a.booked_amount_30d,0)::decimal(18,4) as booked_amount_30d,
       false as historical_catalog_availability_verified
from {{ source('thelook_features', 'products') }} p left join a on p.id=a.product_id
