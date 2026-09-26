<template>
   <div class="app-container">
      <el-form
         ref="queryRef"
         :model="queryParams"
         :rules="queryRules"
         :inline="true"
         v-show="showSearch"
         label-width="80px"
      >
         <el-form-item label="股票代码" prop="code">
            <el-input
               v-model="queryParams.code"
               placeholder="请输入6位股票代码"
               clearable
               maxlength="6"
               style="width: 240px"
               @keyup.enter="handleQuery"
            />
         </el-form-item>
         <el-form-item label="开始日期" prop="start">
            <el-date-picker
               v-model="queryParams.start"
               type="date"
               value-format="YYYY-MM-DD"
               placeholder="请选择开始日期"
               style="width: 180px"
            />
         </el-form-item>
         <el-form-item label="结束日期" prop="end">
            <el-date-picker
               v-model="queryParams.end"
               type="date"
               value-format="YYYY-MM-DD"
               placeholder="请选择结束日期"
               style="width: 180px"
            />
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
            <el-tag type="info">共 {{ total }} 条日线数据</el-tag>
         </el-col>
         <right-toolbar v-model:showSearch="showSearch" @queryTable="getList"></right-toolbar>
      </el-row>

      <el-table v-loading="loading" :data="stockDayList" stripe>
         <el-table-column label="交易日期" align="center" prop="date" width="120" />
         <el-table-column label="股票代码" align="center" prop="code" width="110" />
         <el-table-column label="开盘价" align="right" prop="open" min-width="100">
            <template #default="scope">{{ formatPrice(scope.row.open) }}</template>
         </el-table-column>
         <el-table-column label="最高价" align="right" prop="high" min-width="100">
            <template #default="scope">{{ formatPrice(scope.row.high) }}</template>
         </el-table-column>
         <el-table-column label="最低价" align="right" prop="low" min-width="100">
            <template #default="scope">{{ formatPrice(scope.row.low) }}</template>
         </el-table-column>
         <el-table-column label="收盘价" align="right" prop="close" min-width="100">
            <template #default="scope">{{ formatPrice(scope.row.close) }}</template>
         </el-table-column>
         <el-table-column label="成交量" align="right" prop="volume" min-width="150">
            <template #default="scope">{{ formatNumber(scope.row.volume) }}</template>
         </el-table-column>
         <el-table-column label="成交额" align="right" prop="amount" min-width="160">
            <template #default="scope">{{ formatNumber(scope.row.amount, 2) }}</template>
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

<script setup name="StockDay">
import { importStockDay, listStockDay } from '@/api/system/stockDay'

const DEFAULT_QUERY = {
  code: '002594',
  start: '2025-01-01',
  end: '2026-03-31',
  pageNum: 1,
  pageSize: 10
};

const { proxy } = getCurrentInstance();
const loading = ref(false);
const importLoading = ref(false);
const showSearch = ref(true);
const stockDayList = ref([]);
const total = ref(0);

const validateDateRange = (rule, value, callback) => {
  if (queryParams.value.start && queryParams.value.end && queryParams.value.start > queryParams.value.end) {
    callback(new Error('开始日期不能晚于结束日期'));
    return;
  }
  callback();
};

const data = reactive({
  queryParams: { ...DEFAULT_QUERY },
  queryRules: {
    code: [
      { required: true, message: '股票代码不能为空', trigger: 'blur' },
      { pattern: /^\d{6}$/, message: '股票代码必须为6位数字', trigger: 'blur' }
    ],
    start: [
      { required: true, message: '开始日期不能为空', trigger: 'change' },
      { validator: validateDateRange, trigger: 'change' }
    ],
    end: [
      { required: true, message: '结束日期不能为空', trigger: 'change' },
      { validator: validateDateRange, trigger: 'change' }
    ]
  }
});

const { queryParams, queryRules } = toRefs(data);

/** 查询股票日线数据 */
function getList() {
  loading.value = true;
  listStockDay(queryParams.value).then(response => {
    stockDayList.value = response.rows || [];
    total.value = response.total || 0;
  }).finally(() => {
    loading.value = false;
  });
}

/** 搜索按钮操作 */
function handleQuery() {
  proxy.$refs.queryRef.validate(valid => {
    if (valid) {
      queryParams.value.pageNum = 1;
      getList();
    }
  });
}

/** 重置按钮操作 */
function resetQuery() {
  Object.assign(queryParams.value, DEFAULT_QUERY);
  proxy.resetForm('queryRef');
  getList();
}

/** 获取并导入股票日线数据 */
function handleImport() {
  proxy.$refs.queryRef.validate(valid => {
    if (!valid) {
      return;
    }

    const { code, start, end } = queryParams.value;
    importLoading.value = true;
    importStockDay({ code, start, end }).then(response => {
      proxy.$modal.msgSuccess(response.msg || '获取数据成功');
      queryParams.value.pageNum = 1;
      getList();
    }).finally(() => {
      importLoading.value = false;
    });
  });
}

/** 格式化价格 */
function formatPrice(value) {
  return Number(value).toFixed(2);
}

/** 格式化数值 */
function formatNumber(value, maximumFractionDigits = 0) {
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits });
}

getList();
</script>
