select 'duplicate_pair_day' as problem from {{ ref('dws_user_product_day') }}
group by activity_date,user_id,product_id having count(*)>1
union all
select 'duplicate_pair_profile' from {{ ref('ads_user_product_features') }}
group by as_of_date,user_id,product_id having count(*)>1
union all
select 'future_pair_day' from {{ ref('dws_user_product_day') }}
where activity_date>=date '{{ var("feature_as_of") }}'
union all
select 'pair_window' from {{ ref('ads_user_product_features') }}
where product_views_7d>product_views_30d or days_since_last_interaction<0
union all
select 'session_semantics' from {{ ref('dws_session_behavior') }}
where last_observed_event_at>=timestamptz '{{ var("feature_as_of") }} 00:00:00+00'
   or observed_duration_seconds<0 or session_closure_verified or payment_success_verified or order_attribution_verified
