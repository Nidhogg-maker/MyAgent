-- A placed order item is not verified payment. No final status is used as a historical feature.
select i.id as order_item_id, i.order_id, i.user_id, i.product_id,
       o.created_at as order_time_utc,
       cast(timezone('UTC', o.created_at) as date) as order_date,
       i.created_at as item_time_utc,
       cast(i.sale_price as decimal(18,4)) as booked_item_amount,
       i.status as current_snapshot_item_status,
       timestamptz '{{ var("source_observed_at") }}' as ingested_at,
       o.order_id is null as missing_order,
       u.id is null as unknown_user, p.id is null as unknown_product,
       coalesce(i.user_id != o.user_id, false) as user_mismatch,
       i.sale_price is null or i.sale_price < 0 as invalid_amount,
       coalesce(o.created_at < timestamptz '{{ var("feature_as_of") }} 00:00:00+00'
         and i.created_at < timestamptz '{{ var("feature_as_of") }} 00:00:00+00'
         and o.created_at <= timestamptz '{{ var("source_observed_at") }}'
         and i.created_at <= timestamptz '{{ var("source_observed_at") }}', false) as eligible_before_cutoff
from {{ source('thelook_features', 'order_items') }} i
left join {{ source('thelook_features', 'orders') }} o on i.order_id = o.order_id
left join {{ source('thelook_features', 'users') }} u on i.user_id = u.id
left join {{ source('thelook_features', 'products') }} p on i.product_id = p.id
