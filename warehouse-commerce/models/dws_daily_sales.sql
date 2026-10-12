select order_date, country, traffic_source, category, department,
       count(*) as item_count, sum(booked_item_amount) as booked_item_amount,
       sum(complete_item) as complete_item_count, sum(returned_item) as returned_item_count,
       sum(case when complete_item = 1 then booked_item_amount else 0 end) as complete_item_amount
from {{ ref('fct_order_items') }}
group by order_date, country, traffic_source, category, department
