<template>
  <div class="app-container">
    <!-- 操作栏 -->
    <el-card shadow="never" class="mb8">
      <template #header>
        <div class="card-header">
          <span>多因子选股</span>
          <el-tag type="info" effect="plain">数据来源：Baostock + akshare</el-tag>
        </div>
      </template>

      <div class="action-bar">
        <el-button
          type="primary"
          icon="DataAnalysis"
          :loading="calculating"
          :disabled="weightSaving || (settingsDirty && !settingsValid)"
          @click="handleCalculate"
        >
          {{ calculating ? '计算中...' : '开始计算' }}
        </el-button>
        <el-button icon="Plus" :disabled="!hasResults || calculating" @click="handleAddToPool">
          {{ selectedCodes.length ? `加入股票池（已选${selectedCodes.length}）` : '加入股票池' }}
        </el-button>
        <el-button icon="Refresh" :disabled="calculating" @click="loadLatestBatch">刷新</el-button>
      </div>

      <el-alert
        v-if="batchInfo && batchInfo.degradedFactors && batchInfo.degradedFactors.length > 0"
        :title="`以下因子因数据源问题已降级为中性分：${batchInfo.degradedFactors.join('、')}`"
        type="warning"
        :closable="true"
        show-icon
        class="mt8"
      />
    </el-card>

    <!-- 因子权重配置 -->
    <el-card shadow="never" class="mb8">
      <template #header>
        <div class="card-header">
          <span>因子权重配置</span>
          <div class="weight-actions">
            <el-button
              size="small"
              :disabled="calculating || weightSaving || !settingsDirty"
              @click="discardWeightChanges"
            >
              放弃修改
            </el-button>
            <el-button
              type="primary"
              size="small"
              :loading="weightSaving"
              :disabled="calculating || weightSaving || !settingsDirty || !settingsValid"
              @click="saveWeights"
            >
              保存配置
            </el-button>
          </div>
        </div>
      </template>

      <div class="weights-config">
        <div v-for="item in factorWeights" :key="item.factorName" class="weight-item">
          <div class="weight-item-header">
            <span class="weight-label">{{ item.factorLabel }}</span>
            <el-switch
              v-model="item.enabled"
              :disabled="calculating || weightSaving"
            />
          </div>
          <div class="weight-input">
            <el-input-number
              v-model="item.weight"
              class="weight-number"
              :min="0"
              :max="100"
              :step="0.5"
              :precision="2"
              :controls="false"
              :disabled="calculating || weightSaving || !item.enabled"
            />
            <span class="weight-unit">%</span>
          </div>
        </div>
      </div>

      <div class="threshold-config">
        <div class="threshold-info">
          <span class="weight-label">入选分数阈值</span>
          <span class="text-muted">总分大于等于该值的股票标记为入选</span>
        </div>
        <div class="weight-input">
          <el-input-number
            v-model="selectedThreshold"
            class="threshold-number"
            :min="0"
            :max="100"
            :step="1"
            :precision="2"
            :controls="false"
            :disabled="calculating || weightSaving"
          />
          <span class="weight-unit">分</span>
        </div>
      </div>

      <div class="weight-summary" :class="{ 'weight-invalid': !settingsValid }">
        <span>生效权重合计：<b>{{ weightTotal }}%</b></span>
        <span>入选阈值：<b>{{ selectedThreshold }}分</b></span>
        <span v-if="!weightValid" class="weight-error-text">启用因子权重必须合计为100%</span>
      </div>
    </el-card>

    <!-- 批次信息 -->
    <el-card shadow="never" class="mb8" v-if="batchInfo">
      <div class="batch-info">
        <span>最新计算：{{ batchInfo.calcDate }}</span>
        <el-divider direction="vertical" />
        <span>参与计算：<b>{{ batchInfo.totalCount }}</b> 只</span>
        <el-divider direction="vertical" />
        <span>入选（≥{{ selectedThreshold }}分）：<b class="text-success">{{ batchInfo.selectedCount }}</b> 只</span>
      </div>
    </el-card>

    <!-- 结果表格 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>选股结果</span>
          <div class="result-controls">
            <el-radio-group v-model="selectedOnly" size="small" @change="loadResults">
              <el-radio-button :value="true">仅入选</el-radio-button>
              <el-radio-button :value="false">全部结果</el-radio-button>
            </el-radio-group>
            <el-input
              v-model="keyword"
              placeholder="搜索代码/名称"
              clearable
              size="small"
              style="width: 180px; margin-left: 12px"
              @clear="loadResults"
              @keyup.enter="loadResults"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </div>
        </div>
      </template>

      <el-table
        ref="resultTableRef"
        v-loading="loading"
        :data="resultRows"
        :row-key="tableRowKey"
        border
        stripe
        size="small"
        @sort-change="handleSortChange"
        @selection-change="handleSelectionChange"
        :row-class-name="rowClassName"
      >
        <el-table-column
          type="selection"
          width="45"
          fixed="left"
          :selectable="isRowSelectable"
        />
        <el-table-column prop="code" label="代码" width="80" fixed="left" />
        <el-table-column prop="name" label="名称" width="100" fixed="left" />
        <el-table-column prop="totalScore" label="总分" width="80" sortable="custom" fixed="left">
          <template #default="{ row }">
            <span :class="row.totalScore >= selectedThreshold ? 'text-success font-bold' : ''">{{ row.totalScore }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="roeScore" label="ROE" width="70" align="center" />
        <el-table-column prop="pegScore" label="PEG" width="70" align="center" />
        <el-table-column prop="profitGrowthScore" label="利润增长" width="80" align="center" />
        <el-table-column prop="volumeScore" label="成交量" width="70" align="center" />
        <el-table-column prop="macdScore" label="MACD" width="70" align="center" />
        <el-table-column prop="northboundScore" label="北向持仓" width="70" align="center" />
        <el-table-column prop="industryScore" label="行业" width="70" align="center" />
        <el-table-column prop="industryName" label="行业" width="100" />
        <el-table-column prop="macdSignal" label="MACD信号" width="90" align="center" />
        <el-table-column prop="selected" label="入选" width="70" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.selected" type="success" size="small">入选</el-tag>
            <el-tag v-else type="info" size="small">未入选</el-tag>
          </template>
        </el-table-column>
      </el-table>

      <pagination
        v-show="total > 0"
        v-model:page="pageNum"
        v-model:limit="pageSize"
        :total="total"
        @pagination="loadResults"
      />
    </el-card>

    <!-- 加入股票池对话框 -->
    <el-dialog v-model="poolDialogVisible" title="加入股票池" width="400px">
      <el-form label-width="80px">
        <el-form-item label="股票池名称">
          <el-select v-model="poolName" filterable allow-create placeholder="选择或输入股票池名称" style="width: 100%">
            <el-option v-for="name in poolNames" :key="name.poolName" :label="`${name.poolName} (${name.stockCount})`" :value="name.poolName" />
          </el-select>
        </el-form-item>
        <el-form-item label="加入范围">
          <span class="text-muted">
            <template v-if="selectedCodes.length">
              将把已勾选的 {{ selectedCodes.length }} 只入选股票加入「{{ poolName }}」
            </template>
            <template v-else>
              将把当前批次全部 {{ batchInfo?.selectedCount || 0 }} 只入选股票加入「{{ poolName }}」
            </template>
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="poolDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="poolAdding" @click="confirmAddToPool">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup name="MultiFactor">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  calculateMultiFactor,
  listMultiFactorResults,
  getLatestBatch,
  getFactorWeights,
  updateFactorWeights,
  addMultiFactorToPool,
  listStockPoolNames
} from '@/api/system/multiFactor'

const calculating = ref(false)
const loading = ref(false)
const resultRows = ref([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const selectedOnly = ref(true)
const keyword = ref('')
const batchInfo = ref(null)
const factorWeights = ref([])
const selectedThreshold = ref(90)
const savedWeightSnapshot = ref('')
const weightSaving = ref(false)
const hasResults = ref(false)
const poolDialogVisible = ref(false)
const poolName = ref('default')
const poolNames = ref([])
const poolAdding = ref(false)
const resultTableRef = ref()
const selectedRows = ref([])
let calcTimer = null
let calcPollCount = 0

onMounted(() => {
  loadLatestBatch()
  loadWeights()
})

async function loadLatestBatch() {
  try {
    const res = await getLatestBatch()
    if (res.data) {
      batchInfo.value = res.data
      hasResults.value = true
      loadResults()
    }
  } catch (e) {
    console.warn('获取最新批次失败', e)
  }
}

function snapshotSettings() {
  savedWeightSnapshot.value = JSON.stringify({
    selectedThreshold: selectedThreshold.value,
    weights: factorWeights.value.map(({ factorName, weight, enabled }) => ({
      factorName,
      weight,
      enabled
    }))
  })
}

const weightTotal = computed(() => {
  const total = factorWeights.value.reduce((sum, item) => {
    return item.enabled ? sum + Number(item.weight || 0) : sum
  }, 0)
  return Math.round(total * 100) / 100
})

const weightValid = computed(() => Math.abs(weightTotal.value - 100) <= 0.01)

const settingsValid = computed(() => (
  weightValid.value
  && selectedThreshold.value >= 0
  && selectedThreshold.value <= 100
))

const selectedCodes = computed(() => selectedRows.value.map(row => row.code))

const settingsDirty = computed(() => {
  const current = JSON.stringify({
    selectedThreshold: selectedThreshold.value,
    weights: factorWeights.value.map(({ factorName, weight, enabled }) => ({
      factorName,
      weight,
      enabled
    }))
  })
  return current !== savedWeightSnapshot.value
})

async function loadWeights() {
  try {
    const res = await getFactorWeights()
    factorWeights.value = res.data?.weights || []
    selectedThreshold.value = Number(res.data?.selectedThreshold ?? 90)
    snapshotSettings()
  } catch (e) {
    console.warn('获取计算配置失败', e)
  }
}

async function saveWeights() {
  if (!weightValid.value) {
    ElMessage.warning('启用因子权重必须合计为100%')
    return false
  }
  if (selectedThreshold.value < 0 || selectedThreshold.value > 100) {
    ElMessage.warning('入选分数阈值必须在0到100之间')
    return false
  }

  weightSaving.value = true
  try {
    const weights = factorWeights.value.map(({ factorName, weight, enabled }) => ({
      factorName,
      weight,
      enabled
    }))
    await updateFactorWeights({
      selectedThreshold: selectedThreshold.value,
      weights
    })
    ElMessage.success('计算配置已保存')
    await loadWeights()
    return true
  } catch (e) {
    ElMessage.error(e.msg || '保存计算配置失败')
    return false
  } finally {
    weightSaving.value = false
  }
}

async function discardWeightChanges() {
  await loadWeights()
}

async function loadResults() {
  selectedRows.value = []
  loading.value = true
  try {
    const res = await listMultiFactorResults({
      selectedOnly: selectedOnly.value,
      keyword: keyword.value || undefined,
      pageNum: pageNum.value,
      pageSize: pageSize.value
    })
    resultRows.value = res.rows || []
    total.value = res.total || 0
  } catch (e) {
    console.warn('加载结果失败', e)
  } finally {
    loading.value = false
  }
}

async function handleCalculate() {
  if (settingsDirty.value) {
    if (!settingsValid.value) {
      ElMessage.warning('因子权重或入选阈值配置无效，请调整后再计算')
      return
    }

    try {
      await ElMessageBox.confirm('计算配置已修改但尚未保存，是否保存后开始计算？', '提示', {
        confirmButtonText: '保存并计算',
        cancelButtonText: '取消',
        type: 'warning'
      })
    } catch {
      return
    }

    const saved = await saveWeights()
    if (!saved) return
  }

  calculating.value = true
  const previousBatchId = batchInfo.value?.batchId
  try {
    const res = await calculateMultiFactor()
    ElMessage.info(res.msg || '已开始后台计算，请稍后刷新结果')
    startCalcPolling(previousBatchId)
  } catch (e) {
    calculating.value = false
    ElMessage.error(e.msg || '启动计算失败，请稍后重试')
  }
}

function startCalcPolling(previousBatchId) {
  if (calcTimer) {
    clearTimeout(calcTimer)
    calcTimer = null
  }
  calcPollCount = 0

  const poll = async () => {
    calcPollCount += 1
    try {
      const res = await getLatestBatch()
      const nextBatchId = res.data?.batchId
      if (nextBatchId && nextBatchId !== previousBatchId) {
        batchInfo.value = res.data
        hasResults.value = true
        calculating.value = false
        pageNum.value = 1
        loadResults()
        ElMessage.success(`计算完成！共${res.data.totalCount}只，入选${res.data.selectedCount}只`)
        return
      }
    } catch (e) {
      console.warn('查询计算进度失败', e)
    }

    if (calcPollCount >= 180) {
      calculating.value = false
      ElMessage.warning('后台计算时间较长，可稍后点击“刷新”查看结果')
      return
    }
    calcTimer = setTimeout(poll, 10000)
  }

  poll()
}

onUnmounted(() => {
  if (calcTimer) {
    clearTimeout(calcTimer)
    calcTimer = null
  }
})

function tableRowKey(row) {
  return row.code
}

function isRowSelectable(row) {
  return row.selected === 1
}

function handleSelectionChange(selection) {
  selectedRows.value = selection
}

function clearResultSelection() {
  resultTableRef.value?.clearSelection()
  selectedRows.value = []
}

async function handleAddToPool() {
  const targetCount = selectedCodes.value.length || batchInfo.value?.selectedCount || 0
  if (!targetCount) {
    ElMessage.warning('当前批次没有可加入股票池的入选股票')
    return
  }

  poolDialogVisible.value = true
  try {
    const res = await listStockPoolNames()
    poolNames.value = res.data || []
  } catch (e) {
    console.warn('获取股票池列表失败', e)
  }
}

async function confirmAddToPool() {
  if (!poolName.value) {
    ElMessage.warning('请选择或输入股票池名称')
    return
  }
  poolAdding.value = true
  try {
    const payload = { poolName: poolName.value }
    if (selectedCodes.value.length > 0) {
      payload.codes = selectedCodes.value
    }
    const res = await addMultiFactorToPool(payload)
    ElMessage.success(`已加入股票池「${poolName.value}」：新增${res.data.addedCount}只，跳过${res.data.skippedCount}只`)
    poolDialogVisible.value = false
    clearResultSelection()
  } catch (e) {
    ElMessage.error(e.msg || '加入股票池失败')
  } finally {
    poolAdding.value = false
  }
}

function handleSortChange({ prop, order }) {
  // 暂时只支持前端排序
  if (!prop || !order) return
  resultRows.value.sort((a, b) => {
    const va = a[prop] ?? 0
    const vb = b[prop] ?? 0
    return order === 'ascending' ? va - vb : vb - va
  })
}

function rowClassName({ row }) {
  return row.totalScore >= selectedThreshold.value ? 'row-selected' : ''
}

</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.action-bar {
  display: flex;
  gap: 8px;
}
.weight-actions {
  display: flex;
  gap: 8px;
}
.weights-config {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.weight-item {
  padding: 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
}
.weight-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.weight-label {
  font-size: 14px;
  color: var(--el-text-color-primary);
}
.weight-input {
  display: flex;
  align-items: center;
  gap: 6px;
}
.weight-number {
  flex: 1;
}
.weight-unit {
  color: var(--el-text-color-secondary);
}
.threshold-config {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
}
.threshold-info {
  display: flex;
  align-items: center;
  gap: 8px;
}
.threshold-number {
  width: 120px;
}
.weight-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  font-size: 14px;
  color: var(--el-text-color-regular);
}
.weight-invalid {
  color: var(--el-color-danger);
}
.weight-error-text {
  font-size: 13px;
}
.batch-info {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 14px;
  color: var(--el-text-color-regular);
}
.text-success {
  color: var(--el-color-success);
}
.font-bold {
  font-weight: bold;
}
.text-muted {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.mt8 {
  margin-top: 8px;
}
.result-controls {
  display: flex;
  align-items: center;
}
:deep(.row-selected) {
  background-color: var(--el-color-success-light-9);
}
:deep(.el-table .cell) {
  padding: 0 8px;
}
</style>
