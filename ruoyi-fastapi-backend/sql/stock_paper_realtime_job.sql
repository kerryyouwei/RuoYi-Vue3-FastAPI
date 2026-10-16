-- 模拟盘实时轮循自动买入任务
-- 交易时段（09:30-11:30、13:00-15:00）每分钟执行：按实时行情计算模拟盘信号，信号变化立即自动撮合，
-- 并同步更新账户、持仓、成交与净值快照；非交易日与非交易时段由任务内部自动跳过
-- MySQL / PostgreSQL 均可执行；任务状态默认为正常（0），可在“定时任务管理”页面暂停
insert into sys_job (
    job_name, job_group, job_store, job_executor, invoke_target,
    job_args, job_kwargs, cron_expression, time_zone,
    misfire_grace_time, coalesce, max_instances, status,
    create_by, create_time, update_by, update_time, remark
)
select
    '股票池模拟盘实时轮循', 'default', 'default', 'default',
    'module_task.stock_paper_task.run_stock_paper_realtime',
    '[]', '{}', '0 * * ? * MON-FRI', 'Asia/Shanghai',
    1, false, 1, '0',
    'admin', current_timestamp, '', null,
    '交易时段每分钟轮循模拟盘标的池实时行情，信号变化立即自动撮合并更新账户、持仓、订单与净值快照'
from (select 1) as dummy
where not exists (
    select 1 from sys_job
    where job_name = '股票池模拟盘实时轮循' and job_group = 'default'
);
