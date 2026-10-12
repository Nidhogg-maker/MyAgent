-- Event detail preserves anonymous and bad rows; downstream eligibility is explicit.
with deduplicated as (
  select *, row_number() over (partition by id order by created_at, session_id, sequence_number) as rn
  from {{ source('thelook_features', 'events') }}
), parsed as (
  select *, try_cast(regexp_extract(uri, '^/product/([0-9]+)$', 1) as bigint) as parsed_product_id
  from deduplicated where rn = 1
)
select e.id as event_id, e.session_id, e.sequence_number, e.user_id,
       e.created_at as event_time_utc, cast(timezone('UTC', e.created_at) as date) as event_date,
       lower(trim(e.event_type)) as event_type, e.browser, e.traffic_source,
       e.uri as source_uri, p.id as product_id,
       timestamptz '{{ var("source_observed_at") }}' as ingested_at,
       e.user_id is null as is_anonymous,
       e.user_id is not null and u.id is null as unknown_user,
       e.created_at is null as missing_event_time,
       coalesce(e.created_at > timestamptz '{{ var("source_observed_at") }}', false) as future_at_capture,
       e.event_type = 'product' and p.id is null as invalid_product_reference,
       coalesce(e.created_at < timestamptz '{{ var("feature_as_of") }} 00:00:00+00'
         and e.created_at <= timestamptz '{{ var("source_observed_at") }}', false) as eligible_before_cutoff
from parsed e
left join {{ source('thelook_features', 'users') }} u on e.user_id = u.id
left join {{ source('thelook_features', 'products') }} p on e.parsed_product_id = p.id
