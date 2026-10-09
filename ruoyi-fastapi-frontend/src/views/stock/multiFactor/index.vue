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
        <el-button type="primary" icon="DataAnalysis" :loading="calculating" @click="handleCalculate">
          {{ calculating ? '计算中...' : '开始计算' }}
        </el-button>
        <el-button icon="Plus" :disabled="!hasResults || calculating" @click="handleAddToPool">加入股票池</el-button>
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

    <!-- 因子权重展示 -->
    <el-card shadow="never" class="mb8">
      <template #header><span>因子权重配置</span></template>
      <div class="weights-row">
        <el-tag
          v-for="item in factorWeights"
          :key="item.factorName"
          :type="getWeightTagType(item.weight)"
          effect="plain"
          size="large"
          class="weight-tag"
        >
          {{ item.factorLabel }} {{ item.weight }}%
        </el-tag>
      </div>
    </el-card>

    <!-- 批次信息 -->
    <el-card shadow="never" class="mb8" v-if="batchInfo">
      <div class="batch-info">
        <span>最新计算：{{ batchInfo.calcDate }}</span>
        <el-divider direction="vertical" />
        <span>参与计算：<b>{{ batchInfo.totalCount }}</b> 只</span>
        <el-divider direction="vertical" />
        <span>入选（≥90分）：<b class="text-success">{{ batchInfo.selectedCount }}</b> 只</span>
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
        v-loading="loading"
        :data="resultRows"
        border
        stripe
        size="small"
        @sort-change="handleSortChange"
        :row-class-name="rowClassName"
      >
        <el-table-column prop="code" label="代码" width="80" fixed="left" />
        <el-table-column prop="name" label="名称" width="100" fixed="left" />
        <el-table-column prop="totalScore" label="总分" width="80" sortable="custom" fixed="left">
          <template #default="{ row }">
            <span :class="row.totalScore >= 90 ? 'text-success font-bold' : ''">{{ row.totalScore }}</span>
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
        <el-form-item>
          <span class="text-muted">将把 {{ batchInfo?.selectedCount || 0 }} 只入选股票加入「{{ poolName }}」</span>
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
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  calculateMultiFactor,
  listMultiFactorResults,
  getLatestBatch,
  getFactorWeights,
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
const hasResults = ref(false)
const poolDialogVisible = ref(false)
const poolName = ref('default')
const poolNames = ref([])
const poolAdding = ref(false)

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

async function loadWeights() {
  try {
    const res = await getFactorWeights()
    factorWeights.value = res.data || []
  } catch (e) {
    console.warn('获取权重失败', e)
  }
}

async function loadResults() {
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
  calculating.value = true
  try {
    const res = await calculateMultiFactor()
    ElMessage.success(`计算完成！共${res.data.totalCount}只，入选${res.data.selectedCount}只，耗时${res.data.elapsedSeconds}s`)
    batchInfo.value = {
      batchId: res.data.batchId,
      calcDate: res.data.calcDate,
      totalCount: res.data.totalCount,
      selectedCount: res.data.selectedCount,
      degradedFactors: res.data.degradedFactors
    }
    hasResults.value = true
    pageNum.value = 1
    loadResults()
  } catch (e) {
    ElMessage.error(e.msg || '计算失败，请稍后重试')
  } finally {
    calculating.value = false
  }
}

async function handleAddToPool() {
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
    const res = await addMultiFactorToPool({ poolName: poolName.value })
    ElMessage.success(`已加入股票池「${poolName.value}」：新增${res.data.addedCount}只，跳过${res.data.skippedCount}只`)
    poolDialogVisible.value = false
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
  return row.totalScore >= 90 ? 'row-selected' : ''
}

function getWeightTagType(weight) {
  if (weight >= 20) return 'danger'
  if (weight >= 15) return 'warning'
  if (weight >= 10) return ''
  return 'info'
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
.weights-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.weight-tag {
  font-size: 14px;
  padding: 8px 16px;
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
