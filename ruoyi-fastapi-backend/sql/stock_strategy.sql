-- 股票策略回测表：MySQL / PostgreSQL 均支持 JSON 类型。
create table if not exists stock_strategy_run (
  run_id varchar(36) primary key,
  strategy_name varchar(64) not null,
  code varchar(6) not null,
  start_date varchar(10) not null,
  end_date varchar(10) not null,
  initial_cash bigint not null,
  commission_rate varchar(32) not null,
  stamp_tax_rate varchar(32) not null default '0.001',
  benchmark_code varchar(6),
  strategy_params json not null,
  status varchar(16) not null default 'pending',
  progress bigint not null default 0,
  error_message text,
  summary json,
  curves json,
  trades json,
  run_logs json,
  create_time timestamp(3),
  update_time timestamp(3)
);
create index if not exists ix_stock_strategy_run_name on stock_strategy_run(strategy_name);
create index if not exists ix_stock_strategy_run_status on stock_strategy_run(status);
