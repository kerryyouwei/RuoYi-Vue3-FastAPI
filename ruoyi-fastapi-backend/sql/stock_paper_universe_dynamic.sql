-- 模拟盘标的池动态增删：来源类型字段 + 变更日志表 + 按钮权限
-- 已有库升级：执行一次即可（全新库执行 stock_paper.sql 后再执行本文件的 ALTER 会报列重复，可忽略该语句）

ALTER TABLE stock_paper_universe
  ADD COLUMN source_type varchar(16) not null default 'manual' comment '来源类型 manual/pool/scan_pick/init';

-- 存量来源回填：pool:xxx -> pool；空批次 -> manual；其余非空批次 -> scan_pick
UPDATE stock_paper_universe SET source_type = 'pool' WHERE source_batch_id LIKE 'pool:%';
UPDATE stock_paper_universe SET source_type = 'manual' WHERE source_batch_id IS NULL OR source_batch_id = '';
UPDATE stock_paper_universe SET source_type = 'scan_pick'
WHERE source_type = 'manual' AND source_batch_id IS NOT NULL AND source_batch_id <> '';

create table if not exists stock_paper_universe_log (
  id bigint not null auto_increment comment '记录ID',
  account_id bigint not null comment '账户ID',
  code varchar(6) not null comment '6位股票代码',
  action varchar(8) not null comment '动作 add/remove',
  source_type varchar(16) not null default 'manual' comment '来源类型 manual/pool/scan_pick/api',
  source_ref varchar(64) null comment '来源引用（pool:池名 或 批次ID）',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  key ix_stock_paper_universe_log_account_code (account_id, code),
  key ix_stock_paper_universe_log_account_time (account_id, create_time)
) engine=innodb comment='模拟盘标的池变更日志表';

-- 模拟交易菜单下的标的池加入/移出按钮权限
set @paper_menu_id = (
    select menu_id from sys_menu where menu_name = '模拟交易' and parent_id = 121 limit 1
);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select '标的池加入', @paper_menu_id, 6, '#', '', '', '', 1, 0, 'F', '0', '0', 'stock:paper:universe:add', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (select 1 from sys_menu where menu_name = '标的池加入' and parent_id = @paper_menu_id);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select '标的池移出', @paper_menu_id, 7, '#', '', '', '', 1, 0, 'F', '0', '0', 'stock:paper:universe:remove', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (select 1 from sys_menu where menu_name = '标的池移出' and parent_id = @paper_menu_id);
