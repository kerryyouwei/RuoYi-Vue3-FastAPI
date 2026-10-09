<template>
  <div class="app-container">
    <el-card shadow="never" class="mb8">
      <template #header>
        <div class="card-header">
          <span>模拟交易</span>
          <el-tag type="info" effect="plain">数据来源：QUANTAXIS tdx / 腾讯行情，模拟盘仅供研究，不构成投资建议</el-tag>
        </div>
      </template>

      <div class="action-bar">
        <el-button type="primary" icon="Bell" :loading="signalLoading" @click="handleRunSignal">手动收盘算信号</el-button>
        <el-button type="warning" icon="ShoppingCart" :loading="executeLoading" @click="handleRunExecute">手动开盘撮合</el-button>
        <el-button type="success" icon="Setting" @click="openInitDialog">初始化账户</el-button>
        <el-button icon="Refresh" @click="reloadAll">刷新</el-button>
      </div>

      <el-alert
        v-if="!account"
        title="尚未初始化模拟账户，请点击“初始化账户”选择策略、初始资金与标的池"
        type="warning"
        :closable="false"
        show-icon
      />
      <template v-else>
        <el-row :gutter="16" class="metric-row">
          <el-col :xs="12" :sm="8" :lg="4"><div class="metric"><small>总资产</small><strong>{{ money(account.totalEquity) }}</strong></div></el-col>
          <el-col :xs="12" :sm="8" :lg="4"><div class="metric"><small>现金</small><strong>{{ money(account.cash) }}</strong></div></el-col>
          <el-col :xs="12" :sm="8" :lg="4"><div class="metric"><small>持仓市值</small><strong>{{ money(account.positionValue) }}</strong></div></el-col>
          <el-col :xs="12" :sm="8" :lg="4"><div class="metric"><small>累计收益</small><strong :class="pnlClass">{{ money(account.pnl) }}</strong></div></el-col>
          <el-col :xs="12" :sm="8" :lg="4"><div class="metric"><small>累计收益率</small><strong :class="pnlClass">{{ rate(account.returnRate) }}</strong></div></el-col>
          <el-col :xs="12" :sm="8" :lg="4"><div class="metric"><small>初始资金</small><strong>{{ money(account.initialCash) }}</strong></div></el-col>
        </el-row>
      </template>
    </el-card>

    <el-card shadow="never" class="mb8" v-if="account">
      <template #header><div class="card-header"><span>标的池</span><el-tag type="info" effect="plain">{{ universe.length }} 只</el-tag></div></template>
      <el-alert v-if="!universe.length" title="标的池为空，请先在批量选股回测页勾选加入模拟盘" type="info" :closable="false" show-icon />
      <el-table v-else v-loading="universeLoading" :data="universe" stripe>
        <el-table-column label="股票代码" prop="code" width="110" align="center" />
        <el-table-column label="股票名称" prop="name" width="130" show-overflow-tooltip />
        <el-table-column label="来源批次" prop="sourceBatchId" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.sourceBatchId || '手动初始化' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '有效' : '停用' }}</el-tag></template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="mb8" v-if="account">
      <template #header><div class="card-header"><span>净值曲线</span></div></template>
      <div ref="chartRef" class="chart" v-loading="chartLoading" />
    </el-card>

    <el-card shadow="never" class="mb8" v-if="account">
      <template #header><div class="card-header"><span>当前持仓</span></div></template>
      <el-table v-loading="positionsLoading" :data="positions" stripe>
        <el-table-column label="股票代码" prop="code" width="110" align="center" />
        <el-table-column label="股票名称" prop="name" width="130" show-overflow-tooltip />
        <el-table-column label="持仓数量" prop="quantity" width="100" align="right" />
        <el-table-column label="可卖数量" prop="availableQuantity" width="100" align="right" />
        <el-table-column label="成本价" prop="avgCost" width="100" align="right" />
        <el-table-column label="最新价" prop="lastPrice" width="100" align="right" />
        <el-table-column label="市值" width="110" align="right"><template #default="{ row }">{{ money(row.marketValue) }}</template></el-table-column>
        <el-table-column label="浮动盈亏" width="110" align="right"><template #default="{ row }">{{ money(row.pnl) }}</template></el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="mb8" v-if="account">
      <template #header><div class="card-header"><span>今日信号 / 明日开盘计划</span></div></template>
      <el-table v-loading="signalsLoading" :data="signals" stripe>
        <el-table-column label="信号日期" prop="signalDate" width="110" align="center" />
        <el-table-column label="执行日期" prop="executeDate" width="110" align="center" />
        <el-table-column label="股票代码" prop="code" width="110" align="center" />
        <el-table-column label="股票名称" prop="name" width="130" show-overflow-tooltip />
        <el-table-column label="收盘价" prop="closePrice" width="90" align="right" />
        <el-table-column label="信号" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="signalType(row.signal)">{{ row.signal }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="原因" prop="reason" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="signalStatusType(row.status)">{{ signalStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <pagination
        v-show="signalTotal > 0"
        :total="signalTotal"
        v-model:page="signalQuery.pageNum"
        v-model:limit="signalQuery.pageSize"
        @pagination="loadSignals"
      />
    </el-card>

    <el-card shadow="never" v-if="account">
      <template #header><div class="card-header"><span>成交 / 跳过记录</span></div></template>
      <el-table v-loading="ordersLoading" :data="orders" stripe>
        <el-table-column label="执行日期" prop="executeDate" width="110" align="center" />
        <el-table-column label="信号日期" prop="signalDate" width="110" align="center" />
        <el-table-column label="股票代码" prop="code" width="110" align="center" />
        <el-table-column label="股票名称" prop="name" width="130" show-overflow-tooltip />
        <el-table-column label="方向" prop="side" width="70" align="center">
          <template #default="{ row }"><el-tag :type="row.side === '买入' ? 'danger' : 'success'">{{ row.side }}</el-tag></template>
        </el-table-column>
        <el-table-column label="成交价" prop="price" width="90" align="right" />
        <el-table-column label="数量" prop="quantity" width="90" align="right" />
        <el-table-column label="金额" width="110" align="right"><template #default="{ row }">{{ money(row.amount) }}</template></el-table-column>
        <el-table-column label="佣金" width="90" align="right"><template #default="{ row }">{{ money(row.commission) }}</template></el-table-column>
        <el-table-column label="印花税" width="90" align="right"><template #default="{ row }">{{ money(row.stampTax) }}</template></el-table-column>
        <el-table-column label="状态" prop="executeStatus" width="80" align="center">
          <template #default="{ row }"><el-tag :type="row.executeStatus === '成交' ? 'success' : 'info'">{{ row.executeStatus }}</el-tag></template>
        </el-table-column>
        <el-table-column label="跳过原因" prop="skipReason" min-width="180" show-overflow-tooltip />
      </el-table>
      <pagination
        v-show="orderTotal > 0"
        :total="orderTotal"
        v-model:page="orderQuery.pageNum"
        v-model:limit="orderQuery.pageSize"
        @pagination="loadOrders"
      />
    </el-card>

    <el-dialog v-model="initVisible" title="初始化模拟账户" width="560px" destroy-on-close>
      <el-form ref="initFormRef" :model="initForm" :rules="initRules" label-width="100px" @submit.prevent>
        <el-form-item label="策略" prop="strategyName">
          <el-select v-model="initForm.strategyName" filterable placeholder="请选择信号策略" class="w-full">
            <el-option v-for="item in strategies" :key="item.name" :label="`${item.displayName}（${item.name}）`" :value="item.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="初始资金" prop="initialCash">
          <el-input-number v-model="initForm.initialCash" :min="1000" :step="10000" class="w-full" :controls="false" />
        </el-form-item>
        <el-form-item label="标的代码" prop="codesText">
          <el-input
            v-model="initForm.codesText"
            type="textarea"
            :rows="4"
            placeholder="可选。留空则保留现有标的池；输入则重写标的池。支持逗号/换行/空格分隔"
          />
        </el-form-item>
        <el-form-item label="账户名称">
          <el-input v-model="initForm.accountName" maxlength="64" placeholder="默认 default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="initVisible = false">取消</el-button>
        <el-button type="primary" :loading="initLoading" @click="handleInit">确定初始化</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="StockPaper">
import * as echarts from 'echarts'
import { getAccount, getOrders, getPositions, getSignals, getSnapshot, getUniverse, initAccount, runExecute, runSignal } from '@/api/system/stockPaper'
import { listStrategies } from '@/api/system/strategy'

const { proxy } = getCurrentInstance()
const chartRef = ref(null)
const initFormRef = ref(null)
const strategies = ref([])
const account = ref(null)
const positions = ref([])
const universe = ref([])
const universeLoading = ref(false)
const signals = ref([])
const signalTotal = ref(0)
const orders = ref([])
const orderTotal = ref(0)
const chartLoading = ref(false)
const positionsLoading = ref(false)
const signalsLoading = ref(false)
const ordersLoading = ref(false)
const signalLoading = ref(false)
const executeLoading = ref(false)
const initVisible = ref(false)
const initLoading = ref(false)
let chart = null

const signalQuery = reactive({ pageNum: 1, pageSize: 10 })
const orderQuery = reactive({ pageNum: 1, pageSize: 10 })
const initForm = reactive({
  accountName: 'default',
  strategyName: '',
  initialCash: 1000000,
  codesText: ''
})

const initRules = {
  strategyName: [{ required: true, message: '请选择信号策略', trigger: 'change' }]
}

const money = value => (value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
const rate = value => (value == null ? '—' : `${(value * 100).toFixed(2)}%`)
const pnlClass = computed(() => (account.value?.pnl >= 0 ? 'text-success' : 'text-danger'))
const signalType = signal => ({ 买入: 'danger', 卖出: 'success', 持有: 'info' }[signal] || 'info')
const signalStatusLabel = status => ({ pending: '待执行', executed: '已成交', skipped: '已跳过', expired: '已过期' }[status] || status)
const signalStatusType = status => ({ pending: 'warning', executed: 'success', skipped: 'info', expired: 'info' }[status] || 'info')

function loadStrategies() {
  listStrategies({}).then(response => {
    strategies.value = response.data || []
  })
}

function parseCodes(text) {
  return Array.from(new Set((text || '').split(/[\s,，;；]+/).map(x => x.trim()).filter(x => /^\d{6}$/.test(x))))
}

async function loadAccount() {
  try {
    const response = await getAccount()
    account.value = response.data
  } catch {
    account.value = null
  }
}

function loadPositions() {
  if (!account.value) return
  positionsLoading.value = true
  getPositions().then(response => {
    positions.value = response.data || []
  }).finally(() => {
    positionsLoading.value = false
  })
}

function loadUniverse() {
  if (!account.value) return
  universeLoading.value = true
  getUniverse().then(response => {
    universe.value = response.data || []
  }).finally(() => {
    universeLoading.value = false
  })
}

function loadSignals() {
  if (!account.value) return
  signalsLoading.value = true
  getSignals({ accountName: 'default', pageNum: signalQuery.pageNum, pageSize: signalQuery.pageSize }).then(response => {
    signals.value = response.rows || []
    signalTotal.value = response.total || 0
  }).finally(() => {
    signalsLoading.value = false
  })
}

function loadOrders() {
  if (!account.value) return
  ordersLoading.value = true
  getOrders({ accountName: 'default', pageNum: orderQuery.pageNum, pageSize: orderQuery.pageSize }).then(response => {
    orders.value = response.rows || []
    orderTotal.value = response.total || 0
  }).finally(() => {
    ordersLoading.value = false
  })
}

function loadSnapshot() {
  if (!account.value) return
  chartLoading.value = true
  getSnapshot({ accountName: 'default' }).then(response => {
    renderChart(response.data || [])
  }).finally(() => {
    chartLoading.value = false
  })
}

function renderChart(snapshots) {
  if (!chartRef.value) return
  const dates = snapshots.map(x => x.date)
  const equity = snapshots.map(x => x.totalEquity)
  const ret = snapshots.map(x => x.returnRate)
  chart?.dispose()
  chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['总资产', '累计收益率'] },
    grid: { left: 60, right: 60, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: dates },
    yAxis: [
      { type: 'value', name: '总资产', axisLabel: { formatter: v => (v / 10000).toFixed(0) + '万' } },
      { type: 'value', name: '收益率', axisLabel: { formatter: v => `${(v * 100).toFixed(0)}%` } }
    ],
    series: [
      { name: '总资产', type: 'line', showSymbol: false, data: equity },
      { name: '累计收益率', type: 'line', showSymbol: false, yAxisIndex: 1, data: ret, lineStyle: { type: 'dashed' } }
    ]
  })
}

function reloadAll() {
  loadAccount().then(() => {
    loadUniverse()
    loadPositions()
    loadSignals()
    loadOrders()
    loadSnapshot()
  })
}

async function handleRunSignal() {
  signalLoading.value = true
  try {
    await runSignal()
    proxy.$modal.msgSuccess('收盘信号计算完成')
    await loadAccount()
    signalQuery.pageNum = 1
    loadUniverse()
    loadSignals()
    loadSnapshot()
  } finally {
    signalLoading.value = false
  }
}

async function handleRunExecute() {
  executeLoading.value = true
  try {
    await runExecute()
    proxy.$modal.msgSuccess('开盘撮合完成')
    await loadAccount()
    orderQuery.pageNum = 1
    loadUniverse()
    loadPositions()
    loadOrders()
    loadSnapshot()
  } finally {
    executeLoading.value = false
  }
}

function openInitDialog() {
  Object.assign(initForm, { accountName: 'default', strategyName: '', initialCash: 1000000, codesText: '' })
  initVisible.value = true
}

function handleInit() {
  initFormRef.value?.validate(valid => {
    if (!valid) return
    const codes = parseCodes(initForm.codesText)
    initLoading.value = true
    initAccount({
      accountName: initForm.accountName || 'default',
      strategyName: initForm.strategyName,
      initialCash: initForm.initialCash,
      ...(codes.length ? { codes } : {})
    }).then(() => {
      proxy.$modal.msgSuccess('模拟账户初始化完成')
      initVisible.value = false
      loadAccount().then(() => {
        signalQuery.pageNum = 1
        orderQuery.pageNum = 1
        loadUniverse()
        loadPositions()
        loadSignals()
        loadOrders()
        loadSnapshot()
      })
    }).finally(() => {
      initLoading.value = false
    })
  })
}

onBeforeUnmount(() => chart?.dispose())
loadStrategies()
loadAccount().then(() => {
  loadUniverse()
  loadPositions()
  loadSignals()
  loadOrders()
  loadSnapshot()
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.action-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.metric-row {
  margin-top: 6px;
}
.metric {
  padding: 14px;
  margin-bottom: 12px;
  border-radius: 5px;
  background: var(--el-fill-color-light);
}
.metric small,
.metric strong {
  display: block;
}
.metric strong {
  font-size: 20px;
  margin-top: 6px;
}
.chart {
  height: 360px;
}
.text-success {
  color: var(--el-color-success);
}
.text-danger {
  color: var(--el-color-danger);
}
.w-full {
  width: 100%;
}
.mb8 {
  margin-bottom: 8px;
}
</style>