-- 模拟盘标的池日线同步任务
-- 每个交易日09:15（Asia/Shanghai）开盘前执行：同步标的池所有股票的日线数据到MongoDB，
-- 确保收盘信号计算使用最新K线，避免因日线数据滞后导致收盘价错误
-- MySQL / PostgreSQL 均可执行；任务状态默认为正常（0），可在"定时任务管理"页面暂停
insert into sys_job (
    job_name, job_group, job_store, job_executor, invoke_target,
    job_args, job_kwargs, cron_expression, time_zone,
    misfire_grace_time, coalesce, max_instances, status,
    create_by, create_time, update_by, update_time, remark
)
select
    '模拟盘标的池日线同步', 'default', 'default', 'default',
    'module_task.stock_paper_task.run_stock_paper_daily_sync',
    '[]', '{}', '0 15 9 ? * MON-FRI', 'Asia/Shanghai',
    1, false, 1, '0',
    'admin', current_timestamp, '', null,
    '每个交易日09:15同步模拟盘标的池日线数据到MongoDB，确保收盘信号使用最新K线'
from (select 1) as dummy
where not exists (
    select 1 from sys_job
    where job_name = '模拟盘标的池日线同步' and job_group = 'default'
);
