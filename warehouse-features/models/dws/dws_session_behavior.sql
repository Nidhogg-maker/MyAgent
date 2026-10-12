-- A session spans days. No verified closure or payment/order attribution is inferred.
select session_id,date '{{ var("feature_as_of") }}' as as_of_date,
       min(event_time_utc) as first_observed_event_at,max(event_time_utc) as last_observed_event_at,
       date_diff('second',min(event_time_utc),max(event_time_utc)) as observed_duration_seconds,
       count(*) as event_count,
       count(*) filter(where event_type='product' and not invalid_product_reference) as product_view_count,
       count(distinct product_id) as distinct_viewed_product_count,
       count(*) filter(where event_type='cart') as cart_event_count,
       count(*) filter(where event_type='purchase') as purchase_event_count,
       count(distinct user_id) as observed_user_count,
       case when count(distinct user_id)=1 then min(user_id) else null end as observed_user_id,
       count(*) filter(where is_anonymous) as anonymous_event_count,
       count(distinct user_id)>1 as mixed_user_identity,
       bool_or(event_type='purchase') as has_observed_purchase_event,
       case when bool_or(event_type='purchase') then 'OBSERVED_PURCHASE_EVENT'
            else 'UNKNOWN_NOT_VERIFIED_NEGATIVE' end as purchase_observation,
       false as session_closure_verified,false as order_attribution_verified,
       false as payment_success_verified
from {{ ref('dwd_behavior_event') }}
where eligible_before_cutoff and session_id is not null
group by session_id
