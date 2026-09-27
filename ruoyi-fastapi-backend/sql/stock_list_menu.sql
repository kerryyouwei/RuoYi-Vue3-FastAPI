-- 股票列表菜单
-- 挂在既有“股票管理”目录（menu_id = 121）下
insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '股票列表', 121, 2, 'stockList', 'stock/stockList/index', '', '',
    1, 0, 'C', '0', '0', '', 'list',
    'admin', current_timestamp, '', null, 'A股股票列表菜单'
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '股票列表' and parent_id = 121
);

