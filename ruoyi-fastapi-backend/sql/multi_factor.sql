-- 多因子选股结果表：MySQL
create table if not exists multi_factor_result (
  id bigint not null auto_increment,
  batch_id varchar(32) not null comment '计算批次ID，UUID',
  code varchar(6) not null comment '股票代码',
  name varchar(100) null comment '股票简称',
  total_score decimal(6,2) not null comment '总分',
  roe_score decimal(6,2) null comment 'ROE得分',
  peg_score decimal(6,2) null comment 'PEG得分',
  profit_growth_score decimal(6,2) null comment '利润增长得分',
  volume_score decimal(6,2) null comment '成交量得分',
  macd_score decimal(6,2) null comment 'MACD得分',
  northbound_score decimal(6,2) null comment '北向持仓变化得分',
  industry_score decimal(6,2) null comment '行业景气得分',
  roe_value decimal(10,4) null comment 'ROE值',
  peg_value decimal(10,4) null comment 'PEG值',
  profit_growth_value decimal(10,4) null comment '利润增长值',
  turnover_rate_value decimal(10,4) null comment '换手率值',
  macd_signal varchar(20) null comment 'MACD信号',
  northbound_net decimal(16,2) null comment '北向持仓变化值(万元)',
  industry_name varchar(50) null comment '所属行业',
  industry_growth decimal(10,4) null comment '行业营收增速',
  selected tinyint not null default 0 comment '是否入选(>=90分)',
  factor_degraded varchar(255) null comment '降级因子说明',
  calc_date date not null comment '计算日期',
  create_time datetime(3) null comment '创建时间',
  primary key (id),
  unique key uq_multi_factor_batch_code (batch_id, code),
  key ix_multi_factor_calc_date (calc_date),
  key ix_multi_factor_selected (selected)
) engine=innodb comment='多因子选股结果表';

-- 多因子权重配置表
create table if not exists multi_factor_config (
  id bigint not null auto_increment,
  factor_name varchar(32) not null comment '因子名称',
  factor_weight decimal(5,2) not null comment '权重百分比',
  enabled tinyint not null default 1 comment '是否启用',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  unique key uq_multi_factor_config_name (factor_name)
) engine=innodb comment='多因子权重配置表';

-- 初始化默认权重
insert into multi_factor_config (factor_name, factor_weight, enabled, create_time) values
  ('roe', 22.50, 1, current_timestamp),
  ('peg', 15.00, 1, current_timestamp),
  ('profit_growth', 17.50, 1, current_timestamp),
  ('volume', 10.00, 1, current_timestamp),
  ('macd', 10.00, 1, current_timestamp),
  ('northbound', 10.00, 1, current_timestamp),
  ('industry', 15.00, 1, current_timestamp)
on duplicate key update factor_weight = values(factor_weight);

-- 股票管理 > 多因子选股菜单
insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '多因子选股', 121, 4, 'multiFactor', 'stock/multiFactor/index', '', '',
    1, 0, 'C', '0', '0', 'stock:multiFactor:query', 'chart',
    'admin', current_timestamp, '', null, '基于Baostock多因子加权选股菜单'
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '多因子选股' and parent_id = 121
);

set @multi_factor_menu_id = (
    select menu_id from sys_menu where menu_name = '多因子选股' and parent_id = 121 limit 1
);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '触发计算', @multi_factor_menu_id, 1, '#', '', '', '',
    1, 0, 'F', '0', '0', 'stock:multiFactor:calculate', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '触发计算' and parent_id = @multi_factor_menu_id
);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '结果查询', @multi_factor_menu_id, 2, '#', '', '', '',
    1, 0, 'F', '0', '0', 'stock:multiFactor:list', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '结果查询' and parent_id = @multi_factor_menu_id
);

insert into sys_menu (
    menu_name, parent_id, order_num, path, component, query, route_name,
    is_frame, is_cache, menu_type, visible, status, perms, icon,
    create_by, create_time, update_by, update_time, remark
)
select
    '加入股票池', @multi_factor_menu_id, 3, '#', '', '', '',
    1, 0, 'F', '0', '0', 'stock:multiFactor:poolAdd', '#',
    'admin', current_timestamp, '', null, ''
from (select 1) as dummy
where not exists (
    select 1 from sys_menu where menu_name = '加入股票池' and parent_id = @multi_factor_menu_id
);


-- ============ 本地数据缓存表 ============

-- K线缓存表
create table if not exists multi_factor_kline_cache (
  id bigint not null auto_increment,
  code varchar(12) not null comment 'Baostock代码(sh.600000)',
  pure_code varchar(6) not null comment '6位股票代码',
  trade_date date not null comment '交易日期',
  close decimal(12,4) null comment '收盘价',
  pe_ttm decimal(12,4) null comment 'PE(TTM)',
  pb_mrq decimal(12,4) null comment 'PB(MRQ)',
  turn decimal(12,4) null comment '换手率',
  volume decimal(20,2) null comment '成交量',
  amount decimal(20,2) null comment '成交额',
  create_time datetime(3) null,
  primary key (id),
  unique key uq_mf_kline (code, trade_date),
  key ix_mf_kline_pure_code (pure_code),
  key ix_mf_kline_date (trade_date)
) engine=innodb comment='多因子K线缓存表';

-- 财务数据缓存表
create table if not exists multi_factor_financial_cache (
  id bigint not null auto_increment,
  code varchar(12) not null comment 'Baostock代码',
  pure_code varchar(6) not null comment '6位股票代码',
  year int not null comment '年份',
  quarter int not null comment '季度(1-4)',
  roe_avg decimal(12,4) null comment 'ROE平均',
  np_margin decimal(12,4) null comment '净利润率',
  yoy_ni decimal(12,4) null comment '净利润同比增长',
  yoy_equity decimal(12,4) null comment '净资产同比增长',
  stat_date date null comment '统计日期',
  pub_date date null comment '公告日期',
  create_time datetime(3) null,
  primary key (id),
  unique key uq_mf_fin (code, year, quarter),
  key ix_mf_fin_pure_code (pure_code)
) engine=innodb comment='多因子财务数据缓存表';

-- 行业分类缓存表
create table if not exists multi_factor_industry_cache (
  id bigint not null auto_increment,
  pure_code varchar(6) not null comment '6位股票代码',
  code varchar(12) not null comment 'Baostock代码',
  industry_name varchar(50) not null comment '行业名称',
  industry_type varchar(20) null comment '行业类型',
  update_date date not null comment '更新日期',
  create_time datetime(3) null,
  primary key (id),
  unique key uq_mf_ind (pure_code),
  key ix_mf_ind_date (update_date)
) engine=innodb comment='多因子行业分类缓存表';
