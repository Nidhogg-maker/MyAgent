-- Pre-aggregate views and transactions separately; never multiply detail rows.
with v as (
 select event_date as activity_date,user_id,product_id,count(*) as product_view_count,
        max(event_time_utc) as last_view_at
 from {{ ref('dwd_product_view') }}
 where eligible_before_cutoff and user_id is not null and not unknown_user
 group by 1,2,3
), o as (
 select order_date as activity_date,user_id,product_id,count(*) as placed_item_count,
        count(distinct order_id) as placed_order_count,sum(booked_item_amount) as booked_amount,
        max(order_time_utc) as last_order_at
 from {{ ref('dwd_order_item') }}
 where eligible_before_cutoff and not missing_order and not unknown_user
   and not unknown_product and not user_mismatch and not invalid_amount
 group by 1,2,3
)
select coalesce(v.activity_date,o.activity_date) as activity_date,
       coalesce(v.user_id,o.user_id) as user_id,coalesce(v.product_id,o.product_id) as product_id,
       coalesce(v.product_view_count,0) as product_view_count,
       coalesce(o.placed_item_count,0) as placed_item_count,
       coalesce(o.placed_order_count,0) as placed_order_count,
       coalesce(o.booked_amount,0)::decimal(18,4) as booked_amount,v.last_view_at,o.last_order_at
from v full outer join o using(activity_date,user_id,product_id)
