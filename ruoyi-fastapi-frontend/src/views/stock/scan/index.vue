<template>
  <div class="app-container">
    <el-card shadow="never" class="mb8">
      <template #header>
        <div class="card-header">
          <span>批量选股回测</span>
          <el-tag type="info" effect="plain">数据来源：QUANTAXIS 行情 + Backtrader 策略</el-tag>
        </div>
      </template>

      <el-form ref="runFormRef" :model="form" :rules="rules" label-width="110px" @submit.prevent>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="策略" prop="strategyName">
              <el-select v-model="form.strategyName" filterable placeholder="请选择回测策略" class="w-full">
                <el-option
                  v-for="item in strategies"
                  :key="item.name"
                  :label="`${item.displayName}（${item.name}）`"
                  :value="item.name"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="股票池" prop="poolName">
              <el-select
                v-model="form.poolName"
                filterable
                allow-create
                default-first-option
                placeholder="请选择股票池"
                class="w-full"
              >
                <el-option
                  v-for="item in poolNames"
                  :key="item.poolName"
                  :label="`${item.poolName}（${item.stockCount}）`"
                  :value="item.poolName"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="回测日期" prop="dates">
              <el-date-picker
                v-model="form.dates"
                type="daterange"
                value-format="YYYY-MM-DD"
                range-separator="至"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                class="w-full"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="初始资金" prop="initialCash">
              <el-input-number v-model="form.initialCash" :min="1000" :step="10000" class="w-full" :controls="false" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="手续费率" prop="commissionRate">
              <el-input-number v-model="form.commissionRate" :min="0" :max="0.1" :step="0.0001" :precision="4" :controls="false" class="w-full" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="卖出印花税" prop="stampTaxRate">
              <el-input-number v-model="form.stampTaxRate" :min="0" :max="0.1" :step="0.0001" :precision="4" :controls="false" class="w-full" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="基准代码" prop="benchmarkCode">
              <el-input v-model="form.benchmarkCode" maxlength="6" placeholder="可选，6位代码" class="w-full" />
            </el-form-item>
          </el-col>
        </el-row>

        <div class="action-bar">
          <el-button type="primary" icon="VideoPlay" :loading="submitting" @click="handleRun">开始回测</el-button>
          <el-button icon="Refresh" :disabled="submitting" @click="resetForm">重置</el-button>
        </div>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>回测结果</span>
          <div v-if="batch" class="result-meta">
            <el-tag v-if="batch" :type="statusType(batch.status)">{{ statusLabel(batch.status) }}</el-tag>
            <el-tag type="info" v-if="batch.status === 'running' || batch.status === 'pending'">进度 {{ batch.progress }}%</el-tag>
            <el-tag type="success" v-if="batch.status === 'success'">成功 {{ batch.successCount }} / 失败 {{ batch.failedCount }}</el-tag>
          </div>
        </div>
      </template>

      <el-alert v-if="!batch" title="选择策略与股票池后点击“开始回测”，后台将逐只对池内股票回测" type="info" :closable="false" show-icon />
      <template v-else>
        <div class="table-actions">
          <el-button
            type="primary"
            icon="Plus"
            :disabled="!selectedRows.length || pickLoading"
            :loading="pickLoading"
            @click="handlePick"
          >加入模拟盘</el-button>
          <el-select v-model="query.status" clearable placeholder="状态筛选" class="status-select" @change="handleQuery">
            <el-option label="成功" value="success" />
            <el-option label="失败" value="failed" />
            <el-option label="运行中" value="running" />
            <el-option label="待处理" value="pending" />
          </el-select>
          <el-button icon="Refresh" @click="handleQuery">刷新</el-button>
        </div>

        <el-table
          ref="tableRef"
          v-loading="loading"
          :data="rows"
          stripe
          @selection-change="handleSelectionChange"
          @sort-change="handleSortChange"
        >
          <el-table-column type="selection" width="50" align="center" />
          <el-table-column label="股票代码" prop="code" width="110" align="center" />
          <el-table-column label="股票名称" prop="name" width="130" show-overflow-tooltip />
          <el-table-column label="收益率" prop="returnRate" sortable="custom" width="110" align="right">
            <template #default="{ row }">{{ rate(row.returnRate) }}</template>
          </el-table-column>
          <el-table-column label="年化收益" prop="annualReturn" sortable="custom" width="110" align="right">
            <template #default="{ row }">{{ rate(row.annualReturn) }}</template>
          </el-table-column>
          <el-table-column label="夏普比率" prop="sharpeRatio" sortable="custom" width="110" align="right">
            <template #default="{ row }">{{ fixed(row.sharpeRatio, 2) }}</template>
          </el-table-column>
          <el-table-column label="最大回撤" prop="maxDrawdown" sortable="custom" width="110" align="right">
            <template #default="{ row }">{{ rate(row.maxDrawdown) }}</template>
          </el-table-column>
          <el-table-column label="胜率" prop="winRate" sortable="custom" width="100" align="right">
            <template #default="{ row }">{{ rate(row.winRate) }}</template>
          </el-table-column>
          <el-table-column label="盈亏比" prop="profitLossRatio" width="100" align="right">
            <template #default="{ row }">{{ fixed(row.profitLossRatio, 2) }}</template>
          </el-table-column>
          <el-table-column label="交易次数" prop="tradeCount" sortable="custom" width="100" align="right" />
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="错误信息" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ row.errorMessage || '—' }}</template>
          </el-table-column>
        </el-table>

        <pagination
          v-show="total > 0"
          :total="total"
          v-model:page="query.pageNum"
          v-model:limit="query.pageSize"
          @pagination="loadItems"
        />
      </template>
    </el-card>
  </div>
</template>

<script setup name="StockScan">
import { getScan, getScanItems, pickToPaper, runScan } from '@/api/system/stockScan'
import { listStrategies } from '@/api/system/strategy'
import { listStockPoolNames } from '@/api/system/stockSelector'

const { proxy } = getCurrentInstance()
const runFormRef = ref(null)
const tableRef = ref(null)
const strategies = ref([])
const poolNames = ref([])
const submitting = ref(false)
const loading = ref(false)
const pickLoading = ref(false)
const batch = ref(null)
const rows = ref([])
const total = ref(0)
const selectedRows = ref([])
let timer = null

const DEFAULT_FORM = {
  strategyName: '',
  poolName: '',
  dates: [],
  initialCash: 1000000,
  commissionRate: 0.0003,
  stampTaxRate: 0.001,
  benchmarkCode: ''
}

const DEFAULT_QUERY = {
  pageNum: 1,
  pageSize: 20,
  status: '',
  sortBy: 'returnRate',
  order: 'desc'
}

const form = reactive({ ...DEFAULT_FORM })
const query = reactive({ ...DEFAULT_QUERY })

const rules = {
  strategyName: [{ required: true, message: '请选择回测策略', trigger: 'change' }],
  poolName: [{ required: true, message: '请选择股票池', trigger: 'change' }],
  dates: [{ required: true, type: 'array', message: '请选择回测日期范围', trigger: 'change' }]
}

const statusLabel = status => ({ pending: '待处理', running: '运行中', success: '成功', failed: '失败' }[status] || status)
const statusType = status => ({ pending: 'info', running: 'warning', success: 'success', failed: 'danger' }[status] || 'info')
const rate = value => (value == null ? '—' : `${(value * 100).toFixed(2)}%`)
const fixed = (value, precision) => (value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(precision))

function loadStrategies() {
  listStrategies({}).then(response => {
    strategies.value = response.data || []
  })
}

function loadPoolNames() {
  listStockPoolNames().then(response => {
    poolNames.value = response.data || []
  })
}

function handleRun() {
  runFormRef.value?.validate(valid => {
    if (!valid) return
    if (!form.dates || form.dates.length !== 2) {
      proxy.$modal.msgError('请选择完整的回测日期范围')
      return
    }
    submitting.value = true
    const payload = {
      strategyName: form.strategyName,
      poolName: form.poolName,
      start: form.dates[0],
      end: form.dates[1],
      initialCash: form.initialCash,
      commissionRate: form.commissionRate,
      stampTaxRate: form.stampTaxRate,
      benchmarkCode: form.benchmarkCode || undefined,
      strategyParams: {}
    }
    runScan(payload).then(response => {
      const batchId = response.data?.batchId
      proxy.$modal.msgSuccess('批量回测已提交')
      batch.value = { batchId, status: 'pending', progress: 0 }
      Object.assign(query, { pageNum: 1, status: '' })
      pollBatch(batchId)
    }).finally(() => {
      submitting.value = false
    })
  })
}

function pollBatch(batchId) {
  clearTimeout(timer)
  getScan(batchId).then(response => {
    batch.value = response.data
    if (['pending', 'running'].includes(batch.value?.status)) {
      timer = setTimeout(() => pollBatch(batchId), 1500)
    }
    loadItems()
  })
}

function handleQuery() {
  query.pageNum = 1
  loadItems()
}

function loadItems() {
  if (!batch.value?.batchId) return
  loading.value = true
  getScanItems(batch.value.batchId, {
    pageNum: query.pageNum,
    pageSize: query.pageSize,
    status: query.status || undefined,
    sortBy: query.sortBy,
    order: query.order
  }).then(response => {
    rows.value = response.rows || []
    total.value = response.total || 0
    nextTick(() => tableRef.value?.clearSelection())
  }).finally(() => {
    loading.value = false
  })
}

function handleSelectionChange(selection) {
  selectedRows.value = selection || []
}

function handleSortChange({ prop, order }) {
  if (!prop) return
  query.sortBy = prop
  query.order = order === 'ascending' ? 'asc' : 'desc'
  handleQuery()
}

async function handlePick() {
  if (!selectedRows.value.length) {
    proxy.$modal.msgWarning('请先勾选要加入模拟盘的股票')
    return
  }
  pickLoading.value = true
  try {
    const response = await pickToPaper({
      batchId: batch.value.batchId,
      codes: selectedRows.value.map(row => row.code)
    })
    const result = response.data
    proxy.$modal.msgSuccess(`已加入模拟盘：新增 ${result.addedCount} 只，跳过 ${result.skippedCount} 只`)
  } finally {
    pickLoading.value = false
  }
}

function resetForm() {
  Object.assign(form, DEFAULT_FORM)
  form.dates = []
  proxy.resetForm('runFormRef')
}

onBeforeUnmount(() => clearTimeout(timer))
loadStrategies()
loadPoolNames()
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.result-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}
.action-bar {
  display: flex;
  justify-content: flex-end;
  padding-top: 6px;
}
.table-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.status-select {
  width: 140px;
}
.w-full {
  width: 100%;
}
.mb8 {
  margin-bottom: 8px;
}
</style>