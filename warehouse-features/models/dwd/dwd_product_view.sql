-- A product page visit is not an impression or an ad click.
select event_id, session_id, user_id, product_id, event_time_utc, event_date,
       traffic_source, browser, ingested_at, is_anonymous, unknown_user,
       future_at_capture, eligible_before_cutoff
from {{ ref('dwd_behavior_event') }}
where event_type = 'product' and not invalid_product_reference
