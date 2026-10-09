# 股票池批量回测 → 模拟交易闭环方案

## Summary
在现有“智能选股/股票池/单票回测/实时行情/定时任务”基础之上，补齐一条自动化流水线：**对某个命名股票池批量回测 → 页面展示每只股票指标并人工勾选 → 建立全局单账户模拟盘 → 每日“收盘算信号、次日开盘成交”并提示信号**。回测与模拟交易使用同一策略（页面可选），数据源优先 QUANTAXIS tdx、腾讯 HTTP 兜底，模拟盘为系统级共享单账户、等权分仓。

## 关键改动

### 数据模型（MySQL，SQLAlchemy DO + `create_all` 自动建表 + 独立升级 SQL）
- `stock_scan_batch`：批量回测任务主表（batch_id、strategy_name、pool_name、起止日期、资金/费率、benchmark、status、progress、error）。
- `stock_scan_item`：批内每只股票的回测结果（batch_id、code、name、status、summary JSON，并冗余 `return_rate/annual_return/sharpe_ratio/max_drawdown/win_rate/profit_loss_ratio/trade_count` 便于排序筛选）。
- `stock_paper_account`：模拟账户单行（account_name、strategy_name、initial_cash、cash、status）。
- `stock_paper_universe`：模拟盘标的池（account_id、code、name、source_batch_id、status，唯一 `account_id+code`）——人工勾选后写入，独立于选股用的 `stock_pool_item`。
- `stock_paper_signal`：每日收盘信号（signal_date、code、signal=买入/卖出/持有、target 目标仓位、reason、收盘价、execute_date、status）。
- `stock_paper_position`：持仓（account_id、code、quantity、available_quantity【T+1 可卖量】、avg_cost、last_price，唯一 `account_id+code`）。
- `stock_paper_order`：成交/未成交记录（signal_date、execute_date、side、price、quantity、amount、commission、stamp_tax、execute_status=成交/跳过+原因）。
- `stock_paper_daily_snapshot`：每日净值快照（date、total_equity、cash、position_value、pnl），用于收益曲线。

### 后端接口（新增 controller，前缀 `/stock/scan` 与 `/stock/paper`）
- `POST /stock/scan/run`：入参 `{strategy_name, pool_name, start, end, initial_cash, commission_rate, stamp_tax_rate, benchmark_code?, strategy_params}`，返回 batch_id；后台对池内每只 code 串行/小并发调用现有 `StockStrategyService._run_backtest`，逐只写入 `stock_scan_item` 并更新进度。
- `GET /stock/scan/{batch_id}`：批次状态/进度。
- `GET /stock/scan/{batch_id}/items`：结果列表，支持按冗余指标列排序、分页、ready-only 指标过滤（不回改回测）。
- `POST /stock/scan/items/pick`：人工勾选若干 code 写入 `stock_paper_universe`（返回新增/跳过数量）。
- 模拟盘：`POST /stock/paper/account/init`（重置账户+指定 strategy_name+universe codes+初始资金）、`GET /stock/paper/account`、`/positions`、`/signals?date=..`、`/orders`、`/snapshot`。
- `POST /stock/paper/signal/run`（手动触发一次“收盘算信号”）与 `POST /stock/paper/execute/run`（手动触发一次“次日开盘撮合”），便于手工验证；额定流程中也由定时任务调用同样的函数。

### 每日闭环与策略复用
- 在 `BaseStrategy` 增加统一信号输出（每根 bar 记录期望 `signal` 与 `reason`：买入/卖出/持有），新增 `signal` 服务用“迷你 Backtrader 重放到最新一根K线”读取该值——与回测完全同源，避免为每种策略重复写信号逻辑。
- `module_task/stock_paper_task.py` 暴露两个可被 `invokeTarget` 调用的任务：
  - `run_eod_signal()`：每交易日 15:05，对 universe 每只股票取当日收盘价（QUANTAXIS 日线最新或收盘实时快照），按选定策略算信号并写 `stock_paper_signal`，同时刷新持仓 `last_price` 与当日净值快照。
  - `run_morning_execute()`：每交易日 09:35，读取上一交易日未执行信号，取开盘/实时价（QUANTAXIS tdx 优先、腾讯 `web.ifzq.gtimg.cn` 兜底）撮合成交，更新账户/持仓/订单，落净值快照，并把“买入/卖出/未成交原因”作为当日提示。
- 撮合规则：等权分仓、100 股整数取整、现金校验、佣金万3 + 卖出印花税千1、T+1（当日买入不可卖）、停牌/涨跌停标记为“跳过”并在信号/订单中提示。
- 非交易日判定：任务内按 QUANTAXIS 交易日历或“当日可取得行情”判定，空跑返回。

### 定时任务注册（RuoYi 动态任务）
- 复用现有 APScheduler + `SysJob` 机制，提供 SQL 注册两条 cron（时区 Asia/Shanghai，工作日）：
  - 收盘信号：15:05 → `module_task.stock_paper_task.run_eod_signal`
  - 开盘撮合：09:35 → `module_task.stock_paper_task.run_morning_execute`
- 在 `module_task/__init__.py` 增加 `stock_paper_task` 导入；任务内在非交易日或未初始化模拟盘时跳过。

### 前端
- 新增 `src/views/stock/scan/index.vue`（批量回测选股）：选策略/股票池/日期/资金，触发扫描，结果表展示指标列并支持排序筛选与勾选，“加入模拟盘”按钮写入 universe。
- 新增 `src/views/stock/paper/index.vue`（模拟交易）：账户概览卡（总资产/现金/当日盈亏/累计收益率）、净值曲线、持仓表、今日信号/明日开盘计划（重点“提示交易信号”）、成交记录，支持手动“收盘算信号/开盘撮合”按钮。
- 新增 `src/api/system/stockScan.js`、`src/api/system/stockPaper.js`。
- 菜单 SQL：股票管理 > 批量选股回测、模拟交易；权限：`stock:scan:run/list/pick`、`stock:paper:account/position/signal/order/snapshot`。

## 测试计划
- 后端单测（沿用 `tests/module_stock`）：
  - 批量回测：池内多只 code 依次跑 `_run_backtest`、进度与状态流转、失败单只不影响批次。
  - 信号服务：用合成日线验证 ma/macd/jk 在最新 bar 输出买入/卖出/持有正确。
  - 撮合：等权分仓、100 股取整、现金校验、T+1 禁卖、停牌/涨跌停跳过与提示。
  - 交易日判定、账户/持仓/订单/信号/快照 DAO 读写。
- 集成验证：手动触发“收盘信号→开盘撮合”闭环；两次触发同一信号不重复成交；重置账户；非交易日空跑。
- 质量检查：后端 `pytest tests/module_stock` 与 `ruff check`；前端 `npm run build:prod`。

## 假设与默认值
- 初始资金默认 100 万，佣金万3 + 印花税千1（与回测一致），等权分仓，可在账户初始化时配置。
- T+1 做当日禁卖；停牌/涨跌停不成交直接标记“跳过”并提示，不做挂单排队撮合。
- 模拟盘为系统级共享单账户（与股票池一致，本期不做用户隔离）；股票池/批量回测均不自动触发。
- 信号提示 v1 采用“模拟交易页面展示 + 后端日志”，不做邮件/站内信/webhook（预留扩展）。
- 数据源 QUANTAXIS tdx 优先，腾讯 HTTP 兜底（复用 `youw_test/etf_stop_monitor.py` 已验证接口）。
- 回测与模拟交易使用同一策略并在页面可选；未来回测仍可直接从任意 `stock_pool_item.pool_name + code` 读取标的。
