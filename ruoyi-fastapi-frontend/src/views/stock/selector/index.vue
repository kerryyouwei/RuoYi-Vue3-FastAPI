<template>
  <div class="app-container">
    <el-card shadow="never" class="mb8">
      <template #header>
        <div class="card-header">
          <span>智能选股</span>
          <el-tag type="info" effect="plain">数据来源：同花顺问财</el-tag>
        </div>
      </template>

      <el-form ref="searchRef" :model="searchForm" :rules="searchRules" label-width="110px" @submit.prevent>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="最新价下限" prop="priceMin">
              <el-input-number v-model="searchForm.priceMin" :min="0" :precision="2" :controls="false" placeholder="元" class="w-full" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="最新价上限" prop="priceMax">
              <el-input-number v-model="searchForm.priceMax" :min="0" :precision="2" :controls="false" placeholder="元" class="w-full" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="涨跌幅下限" prop="pctChangeMin">
              <el-input-number v-model="searchForm.pctChangeMin" :min="-100" :max="100" :precision="2" :controls="false" placeholder="%" class="w-full" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="涨跌幅上限" prop="pctChangeMax">
              <el-input-number v-model="searchForm.pctChangeMax" :min="-100" :max="100" :precision="2" :controls="false" placeholder="%" class="w-full" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="成交额下限" prop="amountMin">
              <el-input-number v-model="searchForm.amountMin" :min="0" :precision="2" :controls="false" placeholder="亿元" class="w-full" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="换手率下限" prop="turnoverRateMin">
              <el-input-number v-model="searchForm.turnoverRateMin" :min="0" :max="100" :precision="2" :controls="false" placeholder="%" class="w-full" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="换手率上限" prop="turnoverRateMax">
              <el-input-number v-model="searchForm.turnoverRateMax" :min="0" :max="100" :precision="2" :controls="false" placeholder="%" class="w-full" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12" :lg="8">
            <el-form-item label="MACD金叉" prop="macdGoldenCross">
              <el-switch v-model="searchForm.macdGoldenCross" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="自定义条件" prop="customQuery">
              <el-input
                v-model="searchForm.customQuery"
                type="textarea"
                :rows="3"
                maxlength="1000"
                show-word-limit
                placeholder="可输入问财自然语言条件，例如：所属概念包含人工智能且非ST"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <div class="action-bar">
          <el-button type="primary" icon="Search" :loading="searchLoading" @click="handleSearchClick">搜索</el-button>
          <el-button icon="Refresh" :disabled="searchLoading" @click="resetSearch">重置</el-button>
        </div>
      </el-form>
    </el-card>

    <el-card shadow="never" class="mb8">
      <template #header>
        <div class="card-header">
          <span>选股结果</span>
          <div v-if="searchResult" class="result-meta">
            <el-tag type="info">共 {{ searchResult.codeCount }} 条</el-tag>
            <el-tooltip :content="searchResult.queryText" placement="top">
              <el-button link type="primary">查询条件</el-button>
            </el-tooltip>
          </div>
        </div>
      </template>

      <el-alert v-if="!searchResult" title="请填写至少一个选股条件后查询" type="info" :closable="false" show-icon />
      <template v-else>
        <div class="table-actions">
          <el-select
            v-model="targetPoolName"
            filterable
            allow-create
            default-first-option
            placeholder="目标股票池"
            class="target-pool-select"
          >
            <el-option
              v-for="item in poolNames"
              :key="item.poolName"
              :label="`${item.poolName}（${item.stockCount}）`"
              :value="item.poolName"
            />
          </el-select>
          <el-button
            type="primary"
            icon="Plus"
            :disabled="!selectedRows.length || addLoading"
            :loading="addLoading"
            @click="handleAddToPool"
          >加入股票池</el-button>
        </div>

        <el-table
          ref="resultTableRef"
          v-loading="searchLoading"
          :data="resultRows"
          stripe
          @selection-change="handleSelectionChange"
        >
          <el-table-column type="selection" width="50" align="center" />
          <el-table-column label="股票代码" prop="code" width="110" align="center" />
          <el-table-column label="股票名称" prop="name" width="130" show-overflow-tooltip />
          <el-table-column
            v-for="column in resultColumns"
            :key="column"
            :label="column"
            min-width="130"
            show-overflow-tooltip
          >
            <template #default="scope">{{ formatValue(scope.row.raw?.[column]) }}</template>
          </el-table-column>
        </el-table>

        <pagination
          v-show="searchResult.codeCount > 0"
          :total="searchResult.codeCount"
          v-model:page="searchForm.pageNum"
          v-model:limit="searchForm.pageSize"
          @pagination="handleSearch"
        />
      </template>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>股票池</span>
          <el-tag type="info" effect="plain">已保存 {{ poolNames.length }} 个股票池</el-tag>
        </div>
      </template>

      <el-form :inline="true" :model="poolForm" @submit.prevent>
        <el-form-item label="股票池">
          <el-select
            v-model="poolForm.poolName"
            filterable
            allow-create
            default-first-option
            clearable
            placeholder="默认 default，可输入其他名称"
            class="pool-name-select"
            @change="handlePoolQuery"
          >
            <el-option
              v-for="item in poolNames"
              :key="item.poolName"
              :label="`${item.poolName}（${item.stockCount}）`"
              :value="item.poolName"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="poolForm.keyword" clearable maxlength="100" placeholder="代码或名称" @keyup.enter="handlePoolQuery" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" icon="Search" @click="handlePoolQuery">搜索</el-button>
          <el-button icon="Refresh" @click="resetPoolQuery">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="poolLoading" :data="poolList" stripe>
        <el-table-column label="股票池" prop="poolName" width="150" show-overflow-tooltip />
        <el-table-column label="股票代码" prop="code" width="110" align="center" />
        <el-table-column label="股票名称" prop="name" width="140" show-overflow-tooltip />
        <el-table-column label="选股条件" prop="sourceQuery" min-width="240" show-overflow-tooltip />
        <el-table-column label="数据来源" prop="source" width="120" align="center">
          <template #default="scope">
            <el-tag type="info">{{ scope.row.source === 'iwencai' ? '同花顺问财' : scope.row.source }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="加入时间" prop="createTime" width="180" />
        <el-table-column label="操作" width="90" fixed="right" align="center">
          <template #default="scope">
            <el-button link type="danger" @click="handleDeletePoolItem(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <pagination
        v-show="poolTotal > 0"
        :total="poolTotal"
        v-model:page="poolForm.pageNum"
        v-model:limit="poolForm.pageSize"
        @pagination="loadPool"
      />
    </el-card>
  </div>
</template>

<script setup name="StockSelector">
import { addStockPool, listStockPool, listStockPoolNames, removeStockPool, searchAStock } from '@/api/system/stockSelector'

const DEFAULT_SEARCH = {
  customQuery: '',
  priceMin: undefined,
  priceMax: undefined,
  pctChangeMin: undefined,
  pctChangeMax: undefined,
  amountMin: undefined,
  turnoverRateMin: undefined,
  turnoverRateMax: undefined,
  macdGoldenCross: false,
  pageNum: 1,
  pageSize: 20
};

const DEFAULT_POOL_QUERY = {
  poolName: 'default',
  keyword: '',
  pageNum: 1,
  pageSize: 10
};

const { proxy } = getCurrentInstance();
const searchRef = ref(null);
const resultTableRef = ref(null);
const searchLoading = ref(false);
const addLoading = ref(false);
const poolLoading = ref(false);
const searchResult = ref(null);
const resultRows = ref([]);
const selectedRows = ref([]);
const poolList = ref([]);
const poolTotal = ref(0);
const targetPoolName = ref('default');
const poolNames = ref([]);

const searchForm = reactive({ ...DEFAULT_SEARCH });
const poolForm = reactive({ ...DEFAULT_POOL_QUERY });

const hasSearchCondition = () => {
  const filled = value => value !== undefined && value !== null;
  return Boolean(
    searchForm.customQuery?.trim() ||
    filled(searchForm.priceMin) ||
    filled(searchForm.priceMax) ||
    filled(searchForm.pctChangeMin) ||
    filled(searchForm.pctChangeMax) ||
    filled(searchForm.amountMin) ||
    filled(searchForm.turnoverRateMin) ||
    filled(searchForm.turnoverRateMax) ||
    searchForm.macdGoldenCross
  );
};

const validateRange = (minField, maxField, label) => {
  return (rule, value, callback) => {
    const minValue = searchForm[minField];
    const maxValue = searchForm[maxField];
    if (minValue != null && maxValue != null && minValue > maxValue) {
      callback(new Error(`${label}下限不能大于上限`));
      return;
    }
    callback();
  };
};

const validateRequiredCondition = (rule, value, callback) => {
  if (!hasSearchCondition()) {
    callback(new Error('请至少填写一个选股条件'));
    return;
  }
  callback();
};

const searchRules = {
  customQuery: [{ validator: validateRequiredCondition, trigger: 'change' }],
  priceMin: [{ validator: validateRange('priceMin', 'priceMax', '最新价'), trigger: 'change' }],
  priceMax: [{ validator: validateRange('priceMin', 'priceMax', '最新价'), trigger: 'change' }],
  pctChangeMin: [{ validator: validateRange('pctChangeMin', 'pctChangeMax', '涨跌幅'), trigger: 'change' }],
  pctChangeMax: [{ validator: validateRange('pctChangeMin', 'pctChangeMax', '涨跌幅'), trigger: 'change' }],
  turnoverRateMin: [{ validator: validateRange('turnoverRateMin', 'turnoverRateMax', '换手率'), trigger: 'change' }],
  turnoverRateMax: [{ validator: validateRange('turnoverRateMin', 'turnoverRateMax', '换手率'), trigger: 'change' }]
};

const resultColumns = computed(() => {
  const keys = [];
  const seen = new Set();
  for (const row of resultRows.value || []) {
    for (const key of Object.keys(row.raw || {})) {
      if (['股票代码', '股票简称'].includes(key) || seen.has(key)) {
        continue;
      }
      seen.add(key);
      keys.push(key);
    }
  }
  return keys.slice(0, 12);
});

function handleSearchClick() {
  searchForm.pageNum = 1;
  handleSearch();
}

function handleSearch() {
  searchRef.value?.validate(valid => {
    if (!valid) {
      return;
    }
    searchLoading.value = true;
    searchAStock(searchForm).then(response => {
      searchResult.value = response.data;
      resultRows.value = response.data?.rows || [];
      selectedRows.value = [];
      nextTick(() => resultTableRef.value?.clearSelection());
    }).finally(() => {
      searchLoading.value = false;
    });
  });
}

function resetSearch() {
  Object.assign(searchForm, DEFAULT_SEARCH);
  searchResult.value = null;
  resultRows.value = [];
  selectedRows.value = [];
  proxy.resetForm('searchRef');
  resultTableRef.value?.clearSelection();
}

function handleSelectionChange(selection) {
  selectedRows.value = selection || [];
}

async function handleAddToPool() {
  if (!selectedRows.value.length) {
    proxy.$modal.msgWarning('请先选择要加入股票池的股票');
    return;
  }
  const poolName = targetPoolName.value?.trim() || 'default';
  const payload = {
    poolName,
    items: selectedRows.value.map(row => ({
      code: row.code,
      name: row.name,
      sourceQuery: searchResult.value?.queryText || ''
    }))
  };
  addLoading.value = true;
  try {
    const response = await addStockPool(payload);
    const result = response.data;
    proxy.$modal.msgSuccess(`已加入股票池：新增 ${result.addedCount} 条，跳过 ${result.skippedCount} 条`);
    await loadPoolNames();
    await loadPool();
  } finally {
    addLoading.value = false;
  }
}

function loadPool() {
  poolLoading.value = true;
  listStockPool(poolForm).then(response => {
    poolList.value = response.rows || [];
    poolTotal.value = response.total || 0;
  }).finally(() => {
    poolLoading.value = false;
  });
}

function loadPoolNames() {
  return listStockPoolNames().then(response => {
    poolNames.value = response.data || [];
  });
}

function handlePoolQuery() {
  poolForm.pageNum = 1;
  loadPool();
}

function resetPoolQuery() {
  Object.assign(poolForm, DEFAULT_POOL_QUERY);
  loadPool();
}

function handleDeletePoolItem(row) {
  proxy.$modal.confirm(`确认删除股票池「${row.poolName}」中的 ${row.code} 吗？`).then(() => {
    return removeStockPool(row.id);
  }).then(() => {
    proxy.$modal.msgSuccess('删除成功');
    loadPool();
    loadPoolNames();
  }).catch(() => {});
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  return String(value);
}

loadPool();
loadPoolNames();
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

.target-pool-select {
  width: 220px;
}

.w-full {
  width: 100%;
}

.pool-name-select {
  width: 220px;
}

.mb8 {
  margin-bottom: 8px;
}
</style>






