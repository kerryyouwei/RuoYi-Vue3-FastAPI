-- 股票池轮动策略与滚动验证升级 SQL（MySQL）
-- 与 SQLAlchemy 实体 stock_strategy_do.py / stock_paper_do.py 保持一致。
-- 已有库升级：执行前请先确认对应列/表不存在。

-- 1) 股票策略回测记录：股票池快照
ALTER TABLE stock_strategy_run ADD COLUMN pool_name VARCHAR(64) DEFAULT NULL COMMENT '股票池名称';
ALTER TABLE stock_strategy_run ADD COLUMN pool_codes JSON DEFAULT NULL COMMENT '股票池快照代码JSON';

-- 2) 批量回测批次：组合策略股票池快照
ALTER TABLE stock_scan_batch ADD COLUMN pool_codes JSON DEFAULT NULL COMMENT '股票池快照代码JSON（组合策略批次使用）';

-- 3) 滚动样本外验证记录表
CREATE TABLE IF NOT EXISTS stock_strategy_validation (
  validation_id VARCHAR(36) NOT NULL COMMENT '验证ID',
  strategy_name VARCHAR(64) NOT NULL COMMENT '策略模块名',
  code VARCHAR(6) NOT NULL COMMENT '主时钟/基准代码',
  start_date VARCHAR(10) NOT NULL COMMENT '开始日期',
  end_date VARCHAR(10) NOT NULL COMMENT '结束日期',
  initial_cash BIGINT NOT NULL DEFAULT 100000 COMMENT '初始资金',
  commission_rate VARCHAR(32) NOT NULL DEFAULT '0.0003' COMMENT '手续费率',
  stamp_tax_rate VARCHAR(32) NOT NULL DEFAULT '0.001' COMMENT '卖出印花税率',
  benchmark_code VARCHAR(6) DEFAULT NULL COMMENT '基准代码',
  strategy_params JSON DEFAULT NULL COMMENT '策略参数JSON',
  pool_name VARCHAR(64) DEFAULT NULL COMMENT '股票池名称',
  pool_codes JSON DEFAULT NULL COMMENT '股票池快照代码JSON',
  status VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending/running/success/failed',
  progress BIGINT NOT NULL DEFAULT 0 COMMENT '进度百分比',
  error_message TEXT DEFAULT NULL COMMENT '错误信息',
  windows JSON DEFAULT NULL COMMENT '年度窗口结果JSON',
  summary JSON DEFAULT NULL COMMENT '聚合指标JSON',
  create_time DATETIME(3) DEFAULT NULL COMMENT '创建时间',
  update_time DATETIME(3) DEFAULT NULL COMMENT '更新时间',
  PRIMARY KEY (validation_id),
  KEY ix_stock_strategy_validation_strategy_name (strategy_name),
  KEY ix_stock_strategy_validation_status (status),
  KEY ix_stock_strategy_validation_pool_name (pool_name)
) ENGINE=InnoDB COMMENT='股票策略滚动验证记录表';
