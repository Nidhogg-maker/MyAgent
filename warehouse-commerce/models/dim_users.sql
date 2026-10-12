-- Public synthetic identities remain in raw; Agent-facing dimension omits direct identifiers.
select id as user_id, country, state, city, gender, traffic_source,
       case when age < 18 then 'under_18' when age < 25 then '18_24'
            when age < 35 then '25_34' when age < 45 then '35_44'
            when age < 55 then '45_54' else '55_plus' end as age_band,
       created_at as registered_at
from {{ source('thelook', 'users') }}
