-- 为已有 stock_strategy_run 表增加“卖出印花税率”字段。
-- 默认值：0.001，表示 0.1%。

-- MySQL
alter table stock_strategy_run
  add column stamp_tax_rate varchar(32) not null default '0.001' comment '卖出印花税率' after commission_rate;

-- PostgreSQL（如使用 PostgreSQL，请改用下面语句执行）
-- alter table stock_strategy_run add column stamp_tax_rate varchar(32) not null default '0.001';
-- comment on column stock_strategy_run.stamp_tax_rate is '卖出印花税率';
