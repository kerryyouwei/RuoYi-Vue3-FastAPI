-- 为模拟盘成交/跳过记录表添加成交时间字段
-- 执行一次即可
ALTER TABLE stock_paper_order ADD COLUMN trade_time VARCHAR(8) DEFAULT NULL COMMENT '成交时间(HH:MM:SS)';
