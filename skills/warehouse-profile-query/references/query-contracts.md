# 查询契约

user_profile：user_id × as_of；product_profile：product_id × as_of。
user_product：user_id × product_id × as_of；session：session_id × as_of。
as_of 是排他 UTC 零点，所有历史窗口在它之前；不存在日期版本必须澄清，不自动替换。
数据和元数据来自同一个成功发布目录。读取只有固定 SELECT，可绑定ID，无自由 SQL。
状态历史、真实摄入时刻、生产完整性、商品历史可售性均未验证。
