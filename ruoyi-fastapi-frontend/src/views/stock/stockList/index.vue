<template>
   <div class="app-container">
      <el-form
         ref="queryRef"
         :model="queryParams"
         :inline="true"
         v-show="showSearch"
         label-width="80px"
      >
         <el-form-item label="股票代码" prop="code">
            <el-input
               v-model="queryParams.code"
               placeholder="请输入股票代码"
               clearable
               @keyup.enter="handleQuery"
            />
         </el-form-item>
         <el-form-item label="股票名称" prop="name">
            <el-input
               v-model="queryParams.name"
               placeholder="请输入股票名称"
               clearable
               @keyup.enter="handleQuery"
            />
         </el-form-item>
         <el-form-item label="市场" prop="sse">
            <el-select v-model="queryParams.sse" placeholder="请选择市场" clearable style="width: 120px">
               <el-option label="上海" value="sh" />
               <el-option label="深圳" value="sz" />
            </el-select>
         </el-form-item>
         <el-form-item>
            <el-button type="primary" icon="Search" @click="handleQuery">搜索</el-button>
            <el-button icon="Refresh" @click="resetQuery">重置</el-button>
         </el-form-item>
      </el-form>

      <el-row :gutter="10" class="mb8">
         <el-col :span="1.5">
            <el-button
               type="primary"
               plain
               icon="Download"
               :loading="importLoading"
               @click="handleImport"
            >获取数据</el-button>
         </el-col>
         <el-col :span="1.5">
            <el-tag type="info">共 {{ total }} 只股票</el-tag>
         </el-col>
         <right-toolbar v-model:showSearch="showSearch" @queryTable="getList"></right-toolbar>
      </el-row>

      <el-table v-loading="loading" :data="stockList" stripe>
         <el-table-column label="股票代码" align="center" prop="code" width="110" />
         <el-table-column label="股票名称" align="center" prop="name" min-width="120" show-overflow-tooltip />
         <el-table-column label="市场" align="center" width="90">
            <template #default="scope">
               <el-tag>{{ formatMarket(scope.row.sse) }}</el-tag>
            </template>
         </el-table-column>
         <el-table-column label="上市日期" align="center" prop="ipoDate" width="120" />
         <el-table-column label="退市日期" align="center" prop="outDate" width="120" />
         <el-table-column label="状态" align="center" width="90">
            <template #default="scope">
               <el-tag :type="scope.row.status === '1' ? 'success' : 'danger'">
                  {{ formatStatus(scope.row.status) }}
               </el-tag>
            </template>
         </el-table-column>
      </el-table>

      <pagination
         v-show="total > 0"
         :total="total"
         v-model:page="queryParams.pageNum"
         v-model:limit="queryParams.pageSize"
         @pagination="getList"
      />
   </div>
</template>

<script setup name="StockList">
import { importStockList, listStockList } from '@/api/system/stockList'

const DEFAULT_QUERY = {
  code: '',
  name: '',
  sse: '',
  pageNum: 1,
  pageSize: 10
};

const { proxy } = getCurrentInstance();
const loading = ref(false);
const importLoading = ref(false);
const showSearch = ref(true);
const stockList = ref([]);
const total = ref(0);

const data = reactive({
  queryParams: { ...DEFAULT_QUERY }
});

const { queryParams } = toRefs(data);

/** 查询股票列表 */
function getList() {
  loading.value = true;
  listStockList(queryParams.value).then(response => {
    stockList.value = response.rows || [];
    total.value = response.total || 0;
  }).finally(() => {
    loading.value = false;
  });
}

/** 搜索按钮操作 */
function handleQuery() {
  queryParams.value.pageNum = 1;
  getList();
}

/** 重置按钮操作 */
function resetQuery() {
  Object.assign(queryParams.value, DEFAULT_QUERY);
  proxy.resetForm('queryRef');
  getList();
}

/** 获取并导入股票列表 */
function handleImport() {
  importLoading.value = true;
  importStockList().then(response => {
    proxy.$modal.msgSuccess(response.msg || '获取数据成功');
    queryParams.value.pageNum = 1;
    getList();
  }).finally(() => {
    importLoading.value = false;
  });
}

/** 格式化市场 */
function formatMarket(value) {
  if (value === 'sh') return '上海';
  if (value === 'sz') return '深圳';
  return value || '—';
}

/** 格式化状态 */
function formatStatus(value) {
  return value === '1' ? '上市' : '退市';
}

getList();
</script>
