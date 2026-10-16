-- 股票池 DDE 大单资金通知任务
-- 交易时段每小时第35分钟执行（09:35、10:35、11:35、13:35、14:35），
-- 周一至周五自动执行，节假日由任务内部按星期兜底跳过
-- MySQL / PostgreSQL 均可执行；任务状态默认为正常（0），可在“定时任务管理”页面暂停
insert into sys_job (
    job_name, job_group, job_store, job_executor, invoke_target,
    job_args, job_kwargs, cron_expression, time_zone,
    misfire_grace_time, coalesce, max_instances, status,
    create_by, create_time, update_by, update_time, remark
)
select
    '股票池DDE大单资金通知', 'default', 'default', 'default',
    'module_task.stock_dde_notify_task.send_stock_pool_dde_notify',
    '[]', '{"pool_name": "default", "top_n": 30}', '0 35 9-11,13-14 ? * MON-FRI', 'Asia/Shanghai',
    1, false, 1, '0',
    'admin', current_timestamp, '', null,
    '交易时段每小时推送股票池DDE大单资金飞书卡片，正数红色、负数绿色，涨停股不纳入可交易列表'
from (select 1) as dummy
where not exists (
    select 1 from sys_job
    where job_name = '股票池DDE大单资金通知' and job_group = 'default'
);
