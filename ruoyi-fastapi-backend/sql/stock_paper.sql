-- 批量回测选股（scan）与模拟交易（paper）子系统表：MySQL
-- 与 SQLAlchemy 实体 stock_paper_do.py 保持一致；金额/价格列使用 double，主键/唯一键/索引镜像 ORM 定义。
-- 已有库升级：直接执行本文件即可（create table if not exists）。

create table if not exists stock_scan_batch (
  batch_id varchar(36) not null comment '批次ID',
  strategy_name varchar(64) not null comment '策略模块名',
  pool_name varchar(64) not null comment '股票池名称',
  start_date varchar(10) not null comment '开始日期',
  end_date varchar(10) not null comment '结束日期',
  initial_cash bigint not null default 1000000 comment '初始资金',
  commission_rate varchar(32) not null default '0.0003' comment '手续费率',
  stamp_tax_rate varchar(32) not null default '0.001' comment '卖出印花税率',
  benchmark_code varchar(6) null comment '基准代码',
  strategy_params json null comment '策略参数JSON',
  status varchar(16) not null default 'pending' comment 'pending/running/success/failed',
  progress bigint not null default 0 comment '进度百分比',
  total_count bigint not null default 0 comment '股票总数',
  success_count bigint not null default 0 comment '成功数',
  failed_count bigint not null default 0 comment '失败数',
  error_message text null comment '批次级错误信息',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (batch_id),
  key ix_stock_scan_batch_status (status),
  key ix_stock_scan_batch_strategy_name (strategy_name),
  key ix_stock_scan_batch_pool_name (pool_name)
) engine=innodb comment='批量回测选股批次表';

create table if not exists stock_scan_item (
  id bigint not null auto_increment comment '记录ID',
  batch_id varchar(36) not null comment '批次ID',
  code varchar(6) not null comment '6位股票代码',
  name varchar(100) null comment '股票简称',
  status varchar(16) not null default 'pending' comment 'pending/running/success/failed',
  summary json null comment '回测指标JSON',
  error_message text null comment '错误信息',
  return_rate double null comment '策略收益率',
  annual_return double null comment '年化收益率',
  sharpe_ratio double null comment '夏普比率',
  max_drawdown double null comment '最大回撤',
  win_rate double null comment '胜率',
  profit_loss_ratio double null comment '盈亏比',
  trade_count int null comment '交易次数',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  unique key uq_stock_scan_item_batch_code (batch_id, code),
  key ix_stock_scan_item_batch_id (batch_id),
  key ix_stock_scan_item_code (code)
) engine=innodb comment='批量回测选股结果表';

create table if not exists stock_paper_account (
  id bigint not null auto_increment comment '记录ID',
  account_name varchar(64) not null default 'default' comment '账户名称',
  strategy_name varchar(64) null comment '策略模块名',
  initial_cash bigint not null default 1000000 comment '初始资金',
  cash double not null default 0 comment '可用现金',
  status varchar(16) not null default 'active' comment 'active/inactive',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  unique key uq_stock_paper_account_name (account_name)
) engine=innodb comment='模拟交易账户表';

create table if not exists stock_paper_universe (
  id bigint not null auto_increment comment '记录ID',
  account_id bigint not null comment '账户ID',
  code varchar(6) not null comment '6位股票代码',
  name varchar(100) null comment '股票简称',
  source_batch_id varchar(36) null comment '来源回测批次ID',
  status varchar(16) not null default 'active' comment 'active/inactive',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  unique key uq_stock_paper_universe_account_code (account_id, code),
  key ix_stock_paper_universe_account_id (account_id),
  key ix_stock_paper_universe_code (code)
) engine=innodb comment='模拟盘标的池表';

create table if not exists stock_paper_signal (
  id bigint not null auto_increment comment '记录ID',
  account_id bigint not null comment '账户ID',
  code varchar(6) not null comment '6位股票代码',
  signal_date varchar(10) not null comment '信号产生日期',
  signal varchar(8) not null default '持有' comment '买入/卖出/持有',
  reason varchar(500) null comment '信号原因',
  close_price double null comment '产生信号日收盘价',
  execute_date varchar(10) null comment '执行日期（次一交易日）',
  status varchar(16) not null default 'pending' comment 'pending/executed/skipped/expired',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  unique key uq_stock_paper_signal_account_code_date (account_id, code, signal_date),
  key ix_stock_paper_signal_account_id (account_id),
  key ix_stock_paper_signal_code (code),
  key ix_stock_paper_signal_execute_date (execute_date)
) engine=innodb comment='模拟盘交易信号表';

create table if not exists stock_paper_position (
  id bigint not null auto_increment comment '记录ID',
  account_id bigint not null comment '账户ID',
  code varchar(6) not null comment '6位股票代码',
  name varchar(100) null comment '股票简称',
  quantity bigint not null default 0 comment '持仓数量',
  available_quantity bigint not null default 0 comment '可卖数量（T+1）',
  avg_cost double not null default 0 comment '持仓成本',
  last_price double null comment '最新价',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  unique key uq_stock_paper_position_account_code (account_id, code),
  key ix_stock_paper_position_account_id (account_id),
  key ix_stock_paper_position_code (code)
) engine=innodb comment='模拟盘持仓表';

create table if not exists stock_paper_order (
  id bigint not null auto_increment comment '记录ID',
  account_id bigint not null comment '账户ID',
  code varchar(6) not null comment '6位股票代码',
  name varchar(100) null comment '股票简称',
  signal_date varchar(10) null comment '信号产生日期',
  execute_date varchar(10) not null comment '执行日期',
  side varchar(8) not null comment '买入/卖出',
  price double null comment '成交价',
  quantity bigint not null default 0 comment '成交数量',
  amount double not null default 0 comment '成交金额',
  commission double not null default 0 comment '佣金',
  stamp_tax double not null default 0 comment '印花税',
  execute_status varchar(16) not null default '成交' comment '成交/跳过',
  skip_reason varchar(500) null comment '跳过原因',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  key ix_stock_paper_order_account_date (account_id, execute_date),
  key ix_stock_paper_order_account_id (account_id),
  key ix_stock_paper_order_code (code)
) engine=innodb comment='模拟盘交易记录表';

create table if not exists stock_paper_daily_snapshot (
  id bigint not null auto_increment comment '记录ID',
  account_id bigint not null comment '账户ID',
  date varchar(10) not null comment '快照日期',
  total_equity double not null default 0 comment '总资产',
  cash double not null default 0 comment '现金',
  position_value double not null default 0 comment '持仓市值',
  pnl double null comment '累计盈亏',
  return_rate double null comment '累计收益率',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  unique key uq_stock_paper_snapshot_account_date (account_id, date),
  key ix_stock_paper_snapshot_account_id (account_id)
) engine=innodb comment='模拟盘每日净值快照表';

-- ------------------------------------------------------------------
-- 菜单与按钮权限
-- ------------------------------------------------------------------

-- 股票管理 > 批量选股回测
insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '批量选股回测', 121, 4, 'scan', 'stock/scan/index', '', '',
    1, 0, 'C', '0', '0', 'stock:scan:list', 'chart',
    'admin', current_timestamp, '', null, '股票池批量回测选股菜单'
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '批量选股回测' and parent_id = 121
);

set @scan_menu_id = (
    select menu_id from sys_menu where menu_name = '批量选股回测' and parent_id = 121 limit 1
);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select '批量回测', @scan_menu_id, 1, '#', '', '', '', 1, 0, 'F', '0', '0', 'stock:scan:run', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (select 1 from sys_menu where menu_name = '批量回测' and parent_id = @scan_menu_id);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select '回测结果查看', @scan_menu_id, 2, '#', '', '', '', 1, 0, 'F', '0', '0', 'stock:scan:list', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (select 1 from sys_menu where menu_name = '回测结果查看' and parent_id = @scan_menu_id);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select '勾选加入模拟盘', @scan_menu_id, 3, '#', '', '', '', 1, 0, 'F', '0', '0', 'stock:scan:pick', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (select 1 from sys_menu where menu_name = '勾选加入模拟盘' and parent_id = @scan_menu_id);

-- 股票管理 > 模拟交易
insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '模拟交易', 121, 5, 'paper', 'stock/paper/index', '', '',
    1, 0, 'C', '0', '0', 'stock:paper:list', 'money',
    'admin', current_timestamp, '', null, '模拟交易账户与信号撮合菜单'
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '模拟交易' and parent_id = 121
);

set @paper_menu_id = (
    select menu_id from sys_menu where menu_name = '模拟交易' and parent_id = 121 limit 1
);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select '账户与信号查看', @paper_menu_id, 1, '#', '', '', '', 1, 0, 'F', '0', '0', 'stock:paper:list', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (select 1 from sys_menu where menu_name = '账户与信号查看' and parent_id = @paper_menu_id);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select '账户初始化', @paper_menu_id, 2, '#', '', '', '', 1, 0, 'F', '0', '0', 'stock:paper:account', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (select 1 from sys_menu where menu_name = '账户初始化' and parent_id = @paper_menu_id);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select '持仓查看', @paper_menu_id, 3, '#', '', '', '', 1, 0, 'F', '0', '0', 'stock:paper:position', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (select 1 from sys_menu where menu_name = '持仓查看' and parent_id = @paper_menu_id);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select '手动收盘算信号', @paper_menu_id, 4, '#', '', '', '', 1, 0, 'F', '0', '0', 'stock:paper:signal', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (select 1 from sys_menu where menu_name = '手动收盘算信号' and parent_id = @paper_menu_id);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select '手动开盘撮合', @paper_menu_id, 5, '#', '', '', '', 1, 0, 'F', '0', '0', 'stock:paper:execute', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (select 1 from sys_menu where menu_name = '手动开盘撮合' and parent_id = @paper_menu_id);

-- ------------------------------------------------------------------
-- 定时任务：收盘算信号 + 开盘撮合
-- ------------------------------------------------------------------
insert into sys_job (
    job_name, job_group, job_store, job_executor, invoke_target,
    job_args, job_kwargs, cron_expression, time_zone,
    misfire_grace_time, coalesce, max_instances, status,
    create_by, create_time, update_by, update_time, remark
)
select
    '股票池模拟盘收盘算信号', 'default', 'default', 'default',
    'module_task.stock_paper_task.run_stock_paper_eod_signal',
    '[]', '{}', '0 5 15 ? * MON-FRI', 'Asia/Shanghai',
    1, false, 1, '0',
    'admin', current_timestamp, '', null,
    '每个交易日15:05对模拟盘标的池逐只计算买入/卖出/持有信号，并写入净值快照'
from (select 1) as dummy
where not exists (
    select 1 from sys_job
    where job_name = '股票池模拟盘收盘算信号' and job_group = 'default'
);

insert into sys_job (
    job_name, job_group, job_store, job_executor, invoke_target,
    job_args, job_kwargs, cron_expression, time_zone,
    misfire_grace_time, coalesce, max_instances, status,
    create_by, create_time, update_by, update_time, remark
)
select
    '股票池模拟盘开盘撮合', 'default', 'default', 'default',
    'module_task.stock_paper_task.run_stock_paper_morning_execute',
    '[]', '{}', '0 35 9 ? * MON-FRI', 'Asia/Shanghai',
    1, false, 1, '0',
    'admin', current_timestamp, '', null,
    '每个交易日09:35对前一交易日产生的信号按开盘价撮合模拟交易并写入成交记录'
from (select 1) as dummy
where not exists (
    select 1 from sys_job
    where job_name = '股票池模拟盘开盘撮合' and job_group = 'default'
);