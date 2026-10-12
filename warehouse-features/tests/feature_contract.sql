-- Composite grain, cutoff, and source flags are independently asserted.
select 'duplicate_user_day' as problem from {{ ref('dws_user_behavior_day') }}
group by activity_date,user_id having count(*) > 1
union all
select 'duplicate_product_day' from {{ ref('dws_product_behavior_day') }}
group by activity_date,product_id having count(*) > 1
union all
select 'future_user_day' from {{ ref('dws_user_behavior_day') }}
where activity_date >= date '{{ var("feature_as_of") }}'
union all
select 'future_product_day' from {{ ref('dws_product_behavior_day') }}
where activity_date >= date '{{ var("feature_as_of") }}'
union all
select 'invalid_order_reference' from {{ ref('dwd_order_item') }}
where missing_order or unknown_user or unknown_product or user_mismatch or invalid_amount
union all
select 'invalid_product_view' from {{ ref('dwd_behavior_event') }}
where invalid_product_reference
union all
select 'ads_window_violation' from {{ ref('ads_user_profile_daily') }}
where product_views_7d > product_views_30d or days_since_last_order < 0
