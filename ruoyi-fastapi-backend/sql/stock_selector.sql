-- 智能选股股票池表：MySQL
create table if not exists stock_pool_item (
  id bigint not null auto_increment comment '记录ID',
  pool_name varchar(64) not null default 'default' comment '股票池名称',
  code varchar(6) not null comment '6位股票代码',
  name varchar(100) null comment '股票简称',
  source_query text null comment '加入时的问财查询条件',
  source varchar(32) not null default 'iwencai' comment '数据来源',
  remark varchar(255) null comment '备注',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  unique key uq_stock_pool_item_pool_code (pool_name, code),
  key ix_stock_pool_item_pool_name (pool_name),
  key ix_stock_pool_item_code (code)
) engine=innodb comment='股票池明细表';

-- 股票管理 > 智能选股菜单
insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '智能选股', 121, 3, 'selector', 'stock/selector/index', '', '',
    1, 0, 'C', '0', '0', 'stock:selector:query', 'search',
    'admin', current_timestamp, '', null, '问财智能选股与股票池菜单'
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '智能选股' and parent_id = 121
);

set @selector_menu_id = (
    select menu_id from sys_menu where menu_name = '智能选股' and parent_id = 121 limit 1
);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '股票池查询', @selector_menu_id, 1, '#', '', '', '',
    1, 0, 'F', '0', '0', 'stock:pool:list', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '股票池查询' and parent_id = @selector_menu_id
);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '加入股票池', @selector_menu_id, 2, '#', '', '', '',
    1, 0, 'F', '0', '0', 'stock:pool:add', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '加入股票池' and parent_id = @selector_menu_id
);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '删除股票池记录', @selector_menu_id, 3, '#', '', '', '',
    1, 0, 'F', '0', '0', 'stock:pool:remove', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '删除股票池记录' and parent_id = @selector_menu_id
);
