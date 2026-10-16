-- 为模拟盘飞书企业自建应用通知添加消息凭据表
-- 执行一次即可

create table if not exists stock_feishu_message (
  id bigint not null auto_increment comment '记录ID',
  message_type varchar(20) not null default 'signal' comment 'signal/signal_summary',
  signal_id bigint null comment '关联信号ID，汇总消息为空',
  account_id bigint null comment '账户ID，汇总消息为空',
  code varchar(6) null comment '股票代码，汇总消息为空',
  message_id varchar(128) not null comment '飞书消息ID',
  chat_id varchar(64) null comment '飞书群ID',
  recall_status varchar(16) not null default 'sent' comment 'sent/recalled/failed',
  recall_reason varchar(500) null comment '撤回原因或失败原因',
  recalled_at datetime(3) null comment '撤回时间',
  create_time datetime(3) null comment '创建时间',
  update_time datetime(3) null comment '更新时间',
  primary key (id),
  key ix_stock_feishu_message_signal_id (signal_id),
  key ix_stock_feishu_message_message_id (message_id)
) engine=innodb comment='模拟盘飞书消息凭据表';
