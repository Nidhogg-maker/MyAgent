with views as (
  select event_date as activity_date, product_id, count(*) as product_view_count,
         count(distinct user_id) as logged_in_viewer_count,
         count(*) filter(where user_id is null) as anonymous_view_count,
         max(event_time_utc) as last_view_at
  from {{ ref('dwd_product_view') }}
  where eligible_before_cutoff group by 1,2
), orders as (
  select order_date as activity_date, product_id,
         count(*) as placed_item_count, count(distinct order_id) as placed_order_count,
         sum(booked_item_amount) as booked_amount, max(order_time_utc) as last_order_at
  from {{ ref('dwd_order_item') }}
  where eligible_before_cutoff and not missing_order and not unknown_user
    and not unknown_product and not user_mismatch and not invalid_amount
  group by 1,2
)
select coalesce(v.activity_date,o.activity_date) as activity_date,
       coalesce(v.product_id,o.product_id) as product_id,
       coalesce(v.product_view_count,0) as product_view_count,
       coalesce(v.logged_in_viewer_count,0) as logged_in_viewer_count,
       coalesce(v.anonymous_view_count,0) as anonymous_view_count,
       coalesce(o.placed_item_count,0) as placed_item_count,
       coalesce(o.placed_order_count,0) as placed_order_count,
       coalesce(o.booked_amount,0)::decimal(18,4) as booked_amount,
       v.last_view_at, o.last_order_at
from views v full outer join orders o using(activity_date,product_id)
