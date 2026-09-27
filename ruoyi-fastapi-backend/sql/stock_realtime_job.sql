-- 股票实时行情采集与Jk MA5突破信号任务
-- 每个交易日15:05（Asia/Shanghai）执行：调用QA_fetch_get_stock_realtime采集实时行情写入MongoDB，
-- 再按Jk MA5突破规则分析交易信号并以日志方式打印
-- MySQL / PostgreSQL 均可执行；任务状态默认为正常（0），可在“定时任务管理”页面暂停
insert into sys_job (
    job_name, job_group, job_store, job_executor, invoke_target,
    job_args, job_kwargs, cron_expression, time_zone,
    misfire_grace_time, coalesce, max_instances, status,
    create_by, create_time, update_by, update_time, remark
)
select
    '股票实时行情采集与MA5信号', 'default', 'default', 'default',
    'module_task.stock_realtime_task.collect_stock_realtime_and_signal',
    '[]', '{}', '0 5 15 ? * MON-FRI', 'Asia/Shanghai',
    1, false, 1, '0',
    'admin', current_timestamp, '', null,
    '每个交易日15:05采集实时行情写入MongoDB，按Jk MA5突破规则打印交易信号日志（股票池：000001）'
from (select 1) as dummy
where not exists (
    select 1 from sys_job
    where job_name = '股票实时行情采集与MA5信号' and job_group = 'default'
);
