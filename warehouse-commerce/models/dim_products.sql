select p.id as product_id, p.name as product_name, p.category, p.brand,
       p.department, p.distribution_center_id, d.name as distribution_center,
       cast(p.cost as decimal(18,4)) as current_catalog_cost,
       cast(p.retail_price as decimal(18,4)) as current_retail_price
from {{ source('thelook', 'products') }} p
left join {{ source('thelook', 'distribution_centers') }} d
on p.distribution_center_id = d.id
