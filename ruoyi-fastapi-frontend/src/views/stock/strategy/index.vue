<template>
  <div class="app-container">
    <el-form :inline="true" :model="query" class="mb8">
      <el-form-item label="策略名称"><el-input v-model="query.strategyName" clearable placeholder="名称或模块名" @keyup.enter="getList" /></el-form-item>
      <el-form-item label="分类"><el-select v-model="query.category" clearable placeholder="全部"><el-option label="代码策略" value="code" /></el-select></el-form-item>
      <el-form-item label="运行状态"><el-select v-model="query.status" clearable placeholder="全部"><el-option v-for="item in statuses" :key="item" :label="statusLabel(item)" :value="item" /></el-select></el-form-item>
      <el-form-item><el-button type="primary" icon="Search" @click="getList">搜索</el-button><el-button icon="Refresh" @click="resetQuery">重置</el-button></el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="strategies" stripe>
      <el-table-column label="策略名称" min-width="150"><template #default="{ row }"><div>{{ row.displayName }}</div><small>{{ row.name }}</small></template></el-table-column>
      <el-table-column label="分类" prop="category" width="100"><template #default="{ row }"><el-tag>{{ row.category }}</el-tag></template></el-table-column>
      <el-table-column label="说明" prop="description" min-width="220" show-overflow-tooltip />
      <el-table-column label="修改时间" prop="modifiedTime" width="180" />
      <el-table-column label="历史回测" prop="runCount" width="100" />
      <el-table-column label="最近运行" prop="lastRunTime" width="180"><template #default="{ row }">{{ row.lastRunTime || '—' }}</template></el-table-column>
      <el-table-column label="最近收益" width="110"><template #default="{ row }">{{ rate(row.lastReturnRate) }}</template></el-table-column>
      <el-table-column label="最近状态" width="100"><template #default="{ row }"><el-tag v-if="row.lastStatus" :type="statusType(row.lastStatus)">{{ statusLabel(row.lastStatus) }}</el-tag><span v-else>—</span></template></el-table-column>
      <el-table-column label="操作" width="220" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openDrawer(row, false)">详情</el-button><el-button link type="primary" @click="openDrawer(row, true)">运行策略</el-button><el-button link @click="showHistory(row)">历史</el-button></template></el-table-column>
    </el-table>

    <el-drawer v-model="drawer" :title="detail?.displayName || '策略详情'" size="75%" destroy-on-close>
      <el-row :gutter="20"><el-col :span="13"><h4>只读源码</h4><pre class="source">{{ detail?.sourceCode }}</pre></el-col><el-col :span="11">
        <h4>回测参数</h4><el-form ref="runFormRef" :model="runForm" :rules="rules" label-width="95px">
          <el-form-item label="股票代码" prop="code"><el-input v-model="runForm.code" maxlength="6" placeholder="请输入6位股票代码" /></el-form-item>
          <el-form-item label="日期范围" required><el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" range-separator="至" /></el-form-item>
          <el-form-item label="初始资金" prop="initialCash"><el-input-number v-model="runForm.initialCash" :min="1000" :step="10000" /></el-form-item>
          <el-form-item label="手续费率" prop="commissionRate"><el-input-number v-model="runForm.commissionRate" :min="0" :max="0.1" :step="0.0001" :precision="4" /></el-form-item>
          <el-form-item label="卖出印花税" prop="stampTaxRate"><el-input-number v-model="runForm.stampTaxRate" :min="0" :max="0.1" :step="0.0001" :precision="4" placeholder="0.001表示0.1%" /></el-form-item>
          <el-form-item label="基准代码"><el-input v-model="runForm.benchmarkCode" maxlength="6" placeholder="可选，不填写则不计算" /></el-form-item>
          <el-form-item v-for="parameter in detail?.parameters || []" :key="parameter.name" :label="parameterLabel(parameter.name)">
            <el-switch v-if="parameter.type === 'bool'" v-model="runForm.strategyParams[parameter.name]" />
            <el-input-number v-else-if="['int', 'float'].includes(parameter.type)" v-model="runForm.strategyParams[parameter.name]" :precision="parameter.type === 'int' ? 0 : 4" />
            <el-input v-else v-model="runForm.strategyParams[parameter.name]" />
          </el-form-item>
          <el-button type="primary" :loading="submitting" @click="submitRun">运行回测</el-button><span v-if="runId" class="run-id">运行 ID：{{ runId }}</span>
        </el-form>
      </el-col></el-row>
    </el-drawer>

    <el-card v-if="result" class="result-card" v-loading="polling"><template #header>回测结果 <el-tag :type="statusType(result.status)">{{ statusLabel(result.status) }}</el-tag></template>
      <el-alert v-if="result.status === 'failed'" type="error" :title="result.errorMessage" show-icon><template #default><el-button type="primary" link @click="rerun">重新运行</el-button></template></el-alert>
      <template v-else-if="result.status === 'success'"><el-row :gutter="12"><el-col v-for="card in metricCards" :key="card.label" :xs="12" :sm="8" :md="6"><div class="metric"><small>{{ card.label }}</small><strong>{{ card.value }}</strong></div></el-col></el-row>
      <div ref="chartRef" class="chart" /><el-tabs><el-tab-pane label="成交明细"><el-table :data="result.trades || []"><el-table-column prop="date" label="日期" min-width="100" /><el-table-column prop="code" label="标的" width="100" /><el-table-column prop="side" label="方向" width="80" /><el-table-column prop="price" label="成交价" min-width="90" /><el-table-column prop="size" label="数量" min-width="80" /><el-table-column prop="value" label="成交额" min-width="110" /><el-table-column prop="commission" label="手续费" min-width="90" /><el-table-column prop="cash" label="剩余现金" min-width="120" /><el-table-column prop="accountValue" label="账户权益" min-width="120" /><el-table-column prop="grossPnl" label="毛盈亏" min-width="110" /><el-table-column prop="netPnl" label="净盈亏" min-width="110" /></el-table></el-tab-pane><el-tab-pane label="运行日志"><pre class="logs">{{ (result.logs || []).join('\n') }}</pre></el-tab-pane><el-tab-pane label="历史运行"><el-button link type="primary" @click="showHistory({ name: result.strategyName })">查看该策略全部历史记录</el-button></el-tab-pane></el-tabs></template>
      <p v-else>后台正在运行，当前进度 {{ result.progress }}%</p>
    </el-card>

    <el-dialog v-model="historyVisible" title="历史回测" width="900px"><el-table :data="history"><el-table-column prop="runId" label="运行 ID" min-width="220" /><el-table-column prop="code" label="股票" width="90" /><el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column><el-table-column prop="createTime" label="运行时间" width="180" /><el-table-column label="收益"><template #default="{ row }">{{ rate(row.summary?.returnRate) }}</template></el-table-column><el-table-column label="操作"><template #default="{ row }"><el-button link @click="loadResult(row.runId)">查看结果</el-button></template></el-table-column></el-table><pagination v-show="historyTotal > 0" :total="historyTotal" v-model:page="historyQuery.pageNum" v-model:limit="historyQuery.pageSize" @pagination="loadHistory" /></el-dialog>
  </div>
</template>

<script setup name="StockStrategy">
import * as echarts from 'echarts'
import { getRunDetail, getRunStatus, getStrategy, getStrategyHistory, listStrategies, runStrategy } from '@/api/system/strategy'

const { proxy } = getCurrentInstance()
const route = useRoute()
const loading = ref(false), drawer = ref(false), submitting = ref(false), polling = ref(false), historyVisible = ref(false)
const strategies = ref([]), detail = ref(), result = ref(), runId = ref(''), history = ref([]), historyTotal = ref(0), historyStrategy = ref(''), chartRef = ref(), runFormRef = ref()
const query = reactive({ strategyName: '', category: '', status: '' })
const dates = ref(['2023-01-01', '2024-01-31'])
const historyQuery = reactive({ pageNum: 1, pageSize: 10 })
const runForm = reactive({ strategyName: '', code: '', initialCash: 100000, commissionRate: 0.0003, stampTaxRate: 0.001, benchmarkCode: '', strategyParams: {} })
const statuses = ['pending', 'running', 'success', 'failed']
const rules = { code: [{ required: true, pattern: /^\d{6}$/, message: '请输入6位股票代码', trigger: 'blur' }] }
let timer, chart
const statusLabel = (value) => ({ pending: '等待中', running: '运行中', success: '成功', failed: '失败' }[value] || value)
const statusType = (value) => ({ success: 'success', failed: 'danger', running: 'warning', pending: 'info' }[value])
const rate = (value) => value === null || value === undefined ? '—' : `${(Number(value) * 100).toFixed(2)}%`
const parameterLabels = {
  trade_size: '每笔数量',
  all_in: '全部买入',
  ma_period: 'MA周期',
  breakout_ratio: '突破比例',
  max_trade_count: '最大买卖次数'
}
const parameterLabel = (name) => parameterLabels[name] || name
const metricCards = computed(() => { const s = result.value?.summary || {}; return [{ label: '策略收益', value: rate(s.returnRate) }, { label: '年化收益', value: rate(s.annualReturn) }, { label: '基准收益', value: s.benchmarkReturn == null ? '不计算' : rate(s.benchmarkReturn) }, { label: '超额收益', value: s.excessReturn == null ? '不计算' : rate(s.excessReturn) }, { label: '夏普比率', value: s.sharpeRatio?.toFixed?.(2) ?? '—' }, { label: '最大回撤', value: rate(s.maxDrawdown) }, { label: '胜率', value: rate(s.winRate) }, { label: '盈亏比', value: s.profitLossRatio?.toFixed?.(2) ?? '—' }, { label: '交易次数', value: s.tradeCount ?? '—' }] })
function getList() { loading.value = true; listStrategies(query).then(r => { strategies.value = r.data || [] }).finally(() => { loading.value = false }) }
function resetQuery() { Object.assign(query, { strategyName: '', category: '', status: '' }); getList() }
async function openDrawer(row, immediatelyRun) { detail.value = await getStrategy(row.name).then(r => r.data); Object.assign(runForm, { strategyName: row.name, code: '', initialCash: 100000, commissionRate: 0.0003, stampTaxRate: 0.001, benchmarkCode: '', strategyParams: Object.fromEntries((detail.value.parameters || []).map(x => [x.name, x.default])) }); drawer.value = true; if (immediatelyRun) nextTick(() => runFormRef.value?.$el?.querySelector('input')?.focus()) }
function submitRun() { runFormRef.value.validate(async valid => { if (!valid || !dates.value?.[0] || !dates.value?.[1]) { proxy.$modal.msgError('请选择完整日期范围'); return } submitting.value = true; try { const response = await runStrategy({ ...runForm, start: dates.value[0], end: dates.value[1] }); runId.value = response.data.runId; localStorage.setItem('stockStrategyRunId', runId.value); drawer.value = false; result.value = { runId: runId.value, strategyName: runForm.strategyName, status: 'pending', progress: 0 }; pollResult() } finally { submitting.value = false } }) }
async function pollResult() { clearTimeout(timer); polling.value = true; try { const response = await getRunStatus(runId.value); result.value = response.data; if (['pending', 'running'].includes(result.value.status)) timer = setTimeout(pollResult, 1500); else if (result.value.status === 'success') loadResult(runId.value); else proxy.$modal.msgError(result.value.errorMessage || '回测失败') } catch { polling.value = false } finally { if (!['pending', 'running'].includes(result.value?.status)) polling.value = false } }
async function loadResult(id) { clearTimeout(timer); runId.value = id; localStorage.setItem('stockStrategyRunId', id); result.value = (await getRunDetail(id)).data; historyVisible.value = false; if (result.value.status === 'success') nextTick(renderChart); else if (['pending', 'running'].includes(result.value.status)) pollResult() }
function renderChart() { const c = result.value?.curves; if (!c || !chartRef.value) return; chart?.dispose(); chart = echarts.init(chartRef.value); chart.setOption({ tooltip: { trigger: 'axis' }, legend: { data: ['策略收益', '基准收益', '超额收益', '回撤'] }, xAxis: { type: 'category', data: c.dates }, yAxis: { type: 'value', axisLabel: { formatter: v => `${(v * 100).toFixed(0)}%` } }, series: [{ name: '策略收益', type: 'line', showSymbol: false, data: c.strategyReturn }, ...(c.benchmarkReturn ? [{ name: '基准收益', type: 'line', showSymbol: false, data: c.benchmarkReturn }, { name: '超额收益', type: 'line', showSymbol: false, data: c.excessReturn }] : []), { name: '回撤', type: 'line', showSymbol: false, data: c.drawdown, lineStyle: { type: 'dashed' } }] }) }
async function showHistory(row) { historyStrategy.value = row.name; Object.assign(historyQuery, { pageNum: 1, pageSize: 10 }); await loadHistory(); historyVisible.value = true }
async function loadHistory() { const response = await getStrategyHistory(historyStrategy.value, historyQuery); history.value = response.rows || []; historyTotal.value = response.total || 0 }
async function rerun() { if (result.value?.strategyName) await openDrawer({ name: result.value.strategyName }, true) }
onBeforeUnmount(() => { clearTimeout(timer); chart?.dispose() })
getList()
const savedRunId = route.query.runId || localStorage.getItem('stockStrategyRunId')
if (savedRunId) loadResult(savedRunId).catch(() => localStorage.removeItem('stockStrategyRunId'))
</script>

<style scoped>
.source,.logs{max-height:600px;overflow:auto;padding:14px;background:#1f2937;color:#d1fae5;border-radius:4px;white-space:pre-wrap}.result-card{margin-top:18px}.metric{padding:14px;margin-bottom:12px;border-radius:5px;background:var(--el-fill-color-light)}.metric small,.metric strong{display:block}.metric strong{font-size:20px;margin-top:6px}.chart{height:360px}.run-id{margin-left:12px;color:var(--el-text-color-secondary)}
</style>
