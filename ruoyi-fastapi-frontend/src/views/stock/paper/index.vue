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
        <el-select v-model="currentAccountName" filterable placeholder="选择账户" class="account-select" @change="handleAccountChange">
          <el-option
            v-for="item in accounts"
            :key="item.id"
            :label="item.accountName + (item.status === 'active' ? '（启用）' : '（停用）')"
            :value="item.accountName"
          />
        </el-select>
        <el-button type="primary" icon="Bell" :loading="signalLoading" @click="handleRunSignal">手动收盘算信号</el-button>
        <el-button type="warning" icon="ShoppingCart" :loading="executeLoading" @click="handleRunExecute">手动开盘撮合</el-button>
        <el-button type="danger" icon="Timer" :loading="realtimeLoading" @click="handleRunRealtime">手动实时轮循</el-button>
        <el-button type="info" icon="Download" :loading="syncLoading" @click="handleRunDailySync">同步日线</el-button>
        <el-button type="success" icon="Setting" @click="openInitDialog">初始化/重置</el-button>
        <el-button type="success" plain icon="Plus" @click="openCreateDialog">新建账户</el-button>
        <el-button icon="Tools" @click="openManageDialog">账户管理</el-button>
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
      <template #header>
        <div class="card-header">
          <span>标的池<el-tag type="info" effect="plain" class="ml8">{{ universe.length }} 只</el-tag></span>
          <div class="action-bar" style="margin-bottom: 0">
            <el-radio-group v-model="universeStatus" size="small" @change="loadUniverse">
              <el-radio-button value="active">在池</el-radio-button>
              <el-radio-button value="inactive">已移出</el-radio-button>
              <el-radio-button value="all">全部</el-radio-button>
            </el-radio-group>
            <el-button type="primary" size="small" v-hasPermi="['stock:paper:universe:add']" @click="openUniverseAddDialog">添加标的</el-button>
            <el-button size="small" @click="openUniverseLogDrawer">变更记录</el-button>
          </div>
        </div>
      </template>
      <el-alert v-if="!universe.length" title="标的池为空，可点击右上角「添加标的」从已有股票池挑选或直接输入代码加入" type="info" :closable="false" show-icon />
      <el-table v-else v-loading="universeLoading" :data="universe" stripe>
        <el-table-column label="股票代码" prop="code" width="110" align="center" />
        <el-table-column label="股票名称" prop="name" width="130" show-overflow-tooltip />
        <el-table-column label="来源" width="110" align="center">
          <template #default="{ row }">{{ universeSourceLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="来源批次/池" prop="sourceBatchId" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.sourceBatchId || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="80" align="center">
          <template #default="{ row }"><el-tag :type="row.status === 'active' ? 'success' : 'info'">{{ row.status === 'active' ? '在池' : '已移出' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="isHeld(row.code)" content="持仓中不可移出" placement="top">
              <span><el-button type="danger" size="small" link disabled>移出</el-button></span>
            </el-tooltip>
            <el-button v-else type="danger" size="small" link :loading="removingCode === row.code" v-hasPermi="['stock:paper:universe:remove']" @click="handleRemoveUniverse(row)">移出</el-button>
          </template>
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
      <template #header><div class="card-header"><span>标的池实时行情</span><el-tag type="info" effect="plain">每30秒自动刷新</el-tag></div></template>
      <el-table v-loading="quotesLoading" :data="realtimeQuotes" stripe>
        <el-table-column label="股票代码" prop="code" width="110" align="center" />
        <el-table-column label="股票名称" prop="name" width="130" show-overflow-tooltip />
        <el-table-column label="最新价" prop="price" width="100" align="right" />
        <el-table-column label="快照时间" prop="snapshotTime" width="180" align="center" />
        <el-table-column label="持仓数量" prop="quantity" width="100" align="right" />
        <el-table-column label="成本价" prop="avgCost" width="100" align="right" />
        <el-table-column label="浮动盈亏" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.unrealizedPnl !== null" :class="row.unrealizedPnl >= 0 ? 'text-success' : 'text-danger'">{{ money(row.unrealizedPnl) }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="盈亏比例" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.unrealizedPnlRate !== null" :class="row.unrealizedPnlRate >= 0 ? 'text-success' : 'text-danger'">{{ (row.unrealizedPnlRate * 100).toFixed(2) }}%</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="mb8" v-if="account">
      <template #header><div class="card-header"><span>今日信号 / 明日开盘计划</span></div></template>
      <el-table v-loading="signalsLoading" :data="signals" stripe>
        <el-table-column label="信号日期" prop="signalDate" width="110" align="center" />
        <el-table-column label="信号时间" prop="signalTime" width="90" align="center" />
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
            <el-tag :type="signalStatusType(row.status)">{{ signalStatusLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="飞书通知" width="110" align="center">
          <template #default="{ row }">
            <el-button
              v-if="row.signal !== '持有'"
              link
              type="danger"
              :loading="recallLoadingId === row.id"
              @click="handleRecallSignal(row)"
            >
              撤回
            </el-button>
            <span v-else>-</span>
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
        <el-table-column label="成交时间" prop="tradeTime" width="90" align="center" />
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

    <el-dialog v-model="initVisible" :title="initDialogTitle" width="560px" destroy-on-close>
      <el-form ref="initFormRef" :model="initForm" :rules="initRules" label-width="100px" @submit.prevent>
        <el-form-item label="策略" prop="strategyName">
          <el-select v-model="initForm.strategyName" filterable placeholder="请选择信号策略" class="w-full">
            <el-option v-for="item in strategies" :key="item.name" :label="`${item.displayName}（${item.name}）`" :value="item.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="初始资金" prop="initialCash">
          <el-input-number v-model="initForm.initialCash" :min="1000" :step="10000" class="w-full" :controls="false" />
        </el-form-item>
        <el-form-item v-if="initStrategyIsPortfolio" label="选择股票池" prop="poolName">
          <el-select
            v-model="initForm.poolName"
            filterable
            clearable
            placeholder="可选，直接使用已有股票池"
            :loading="poolLoading"
            class="w-full"
            @visible-change="handlePoolDropdown"
          >
            <el-option
              v-for="pool in poolNames"
              :key="pool.poolName"
              :label="`${pool.poolName}（${pool.stockCount}只）`"
              :value="pool.poolName"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标的代码" prop="codesText">
          <el-input
            v-model="initForm.codesText"
            type="textarea"
            :rows="4"
            :placeholder="codesPlaceholder"
          />
        </el-form-item>
        <el-alert
          v-if="initForm.poolName"
          :title="`将把股票池「${initForm.poolName}」全部标的写入标的池（来源显示为 pool:${initForm.poolName}），与标的代码手动输入内容合并去重`"
          type="info"
          :closable="false"
          show-icon
          class="mb8"
        />
        <el-form-item label="账户名称" prop="accountName">
          <el-input v-model="initForm.accountName" maxlength="64" placeholder="输入账户名称" />
        </el-form-item>
        <el-alert
          v-if="initMode === 'reset'"
          title="账户已存在：提交后将清空该账户的持仓/成交/信号/净值历史，请谨慎操作"
          type="warning"
          :closable="false"
          show-icon
          class="mb8"
        />
      </el-form>
      <template #footer>
        <el-button @click="initVisible = false">取消</el-button>
        <el-button type="primary" :loading="initLoading" @click="handleInit">
          {{ initMode === 'create' ? '创建账户' : '确认初始化' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="manageVisible" title="账户管理" width="860px" destroy-on-close>
      <el-table :data="manageRows" stripe>
        <el-table-column label="账户名称" prop="accountName" min-width="120" />
        <el-table-column label="信号策略" min-width="200">
          <template #default="{ row }">
            <el-select v-model="row.strategyName" filterable size="small" class="w-full">
              <el-option v-for="item in strategies" :key="item.name" :label="item.displayName + '（' + item.name + '）'" :value="item.name" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.status" active-value="active" inactive-value="inactive" />
          </template>
        </el-table-column>
        <el-table-column label="总资产" width="130" align="right">
          <template #default="{ row }">{{ money(row.totalEquity) }}</template>
        </el-table-column>
        <el-table-column label="累计收益率" width="110" align="right">
          <template #default="{ row }">{{ rate(row.returnRate) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" align="center">
          <template #default="{ row }">
            <el-button link type="primary" :loading="manageSavingId === row.id" @click="saveManageRow(row)">保存</el-button>
            <el-button link type="danger" :disabled="manageRows.length <= 1" @click="handleDeleteAccount(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="universeAddVisible" title="添加标的到标的池" width="780px">
      <el-tabs v-model="universeAddTab">
        <el-tab-pane label="从股票池挑选" name="pool">
          <el-form :inline="true" @submit.prevent>
            <el-form-item label="股票池">
              <el-select v-model="pickerPoolName" filterable placeholder="请选择股票池" style="width: 240px" @change="handlePickerPoolChange">
                <el-option v-for="item in poolNames" :key="item.poolName" :label="`${item.poolName}（${item.stockCount}）`" :value="item.poolName" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button :disabled="!pickerPoolName" icon="Search" @click="loadPickerRows">刷新</el-button>
            </el-form-item>
          </el-form>
          <el-table v-loading="pickerLoading" :data="pickerRows" stripe max-height="320" @selection-change="handlePickerSelectionChange">
            <el-table-column type="selection" width="45" :selectable="row => !activeUniverseCodes.has(row.code)" />
            <el-table-column label="股票代码" prop="code" width="110" align="center" />
            <el-table-column label="股票名称" prop="name" width="140" show-overflow-tooltip />
            <el-table-column label="数据来源" prop="source" width="110" align="center" />
            <el-table-column label="备注" prop="remark" min-width="140" show-overflow-tooltip />
            <el-table-column label="状态" width="90" align="center">
              <template #default="{ row }">
                <el-tag v-if="activeUniverseCodes.has(row.code)" type="success" size="small">已在池</el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="pickerQuery.pageNum"
            :page-size="pickerQuery.pageSize"
            :total="pickerTotal"
            layout="total, prev, pager, next"
            class="mt8"
            @current-change="loadPickerRows"
          />
          <div class="picker-tip">不勾选任何标的时，将把所选股票池整体加入</div>
        </el-tab-pane>
        <el-tab-pane label="直接输入代码" name="manual">
          <el-input v-model="manualCodesText" type="textarea" :rows="5" placeholder="支持逗号/换行/空格分隔，如：600519,000001" />
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="universeAddVisible = false">取消</el-button>
        <el-button type="primary" :loading="universeAddLoading" @click="handleUniverseAdd">加入</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="universeLogVisible" title="标的池变更记录" size="600px">
      <el-table v-loading="universeLogLoading" :data="universeLogs" stripe>
        <el-table-column label="时间" prop="createTime" width="170" align="center" />
        <el-table-column label="代码" prop="code" width="90" align="center" />
        <el-table-column label="动作" width="70" align="center">
          <template #default="{ row }"><el-tag :type="row.action === 'add' ? 'success' : 'danger'" size="small">{{ row.action === 'add' ? '加入' : '移出' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="来源" prop="sourceType" width="90" align="center" />
        <el-table-column label="来源引用" prop="sourceRef" min-width="130" show-overflow-tooltip />
      </el-table>
      <el-pagination
        v-model:current-page="universeLogQuery.pageNum"
        :page-size="universeLogQuery.pageSize"
        :total="universeLogTotal"
        layout="total, prev, pager, next"
        class="mt8"
        @current-change="loadUniverseLogs"
      />
    </el-drawer>
  </div>
</template>

<script setup name="StockPaper">
import * as echarts from 'echarts'
import {
  addToUniverse,
  createAccount,
  deleteAccount,
  getAccount,
  getOrders,
  getPositions,
  getSignals,
  getSnapshot,
  getRealtimeQuotes,
  getUniverse,
  getUniverseLogs,
  initAccount,
  listAccounts,
  recallSignalNotification,
  removeFromUniverse,
  runDailySync,
  runExecute,
  runRealtime,
  runSignal,
  updateAccount,
} from '@/api/system/stockPaper'
import { listStockPool, listStockPoolNames } from '@/api/system/stockSelector'
import { listStrategies } from '@/api/system/strategy'

const { proxy } = getCurrentInstance()
const chartRef = ref(null)
const initFormRef = ref(null)
const strategies = ref([])
const poolNames = ref([])
const poolLoading = ref(false)
const account = ref(null)
const accounts = ref([])
const currentAccountName = ref('default')
const initMode = ref('reset')
const manageVisible = ref(false)
const manageRows = ref([])
const manageSavingId = ref(null)
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
const realtimeLoading = ref(false)
const recallLoadingId = ref(null)
const syncLoading = ref(false)
const realtimeQuotes = ref([])
const quotesLoading = ref(false)
const initVisible = ref(false)
const initLoading = ref(false)
const universeStatus = ref('active')
const removingCode = ref(null)
const universeAddVisible = ref(false)
const universeAddLoading = ref(false)
const universeAddTab = ref('pool')
const pickerPoolName = ref('')
const pickerRows = ref([])
const pickerLoading = ref(false)
const pickerTotal = ref(0)
const pickerSelection = ref([])
const manualCodesText = ref('')
const universeLogVisible = ref(false)
const universeLogLoading = ref(false)
const universeLogs = ref([])
const universeLogTotal = ref(0)
const pickerQuery = reactive({ pageNum: 1, pageSize: 20 })
const universeLogQuery = reactive({ pageNum: 1, pageSize: 10 })
let chart = null
let refreshTimer = null
let quotesTimer = null

const signalQuery = reactive({ pageNum: 1, pageSize: 10 })
const orderQuery = reactive({ pageNum: 1, pageSize: 10 })
const initForm = reactive({
  accountName: 'default',
  strategyName: '',
  initialCash: 1000000,
  codesText: '',
  poolName: ''
})

const initRules = {
  strategyName: [{ required: true, message: '请选择信号策略', trigger: 'change' }],
  accountName: [{ required: true, message: '请输入账户名称', trigger: 'blur' }],
  codesText: [
    {
      validator: (_rule, value, callback) => {
        if (initMode.value === 'create' && !initForm.poolName && !parseCodes(value || '').length) {
          callback(new Error('请选择已有股票池或输入标的代码'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ]
}

const initDialogTitle = computed(() => (initMode.value === 'create' ? '新建模拟账户' : '初始化/重置模拟账户'))
const initStrategyIsPortfolio = computed(() => strategies.value.find(item => item.name === initForm.strategyName)?.isPortfolio ?? false)
const codesPlaceholder = computed(() =>
  initForm.poolName
    ? '可选。与所选股票池合并去重；支持逗号/换行/空格分隔'
    : '可选。留空则保留现有标的池；输入则重写标的池。支持逗号/换行/空格分隔'
)

const money = value => (value == null || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
const rate = value => (value == null ? '—' : `${(value * 100).toFixed(2)}%`)
const pnlClass = computed(() => (account.value?.pnl >= 0 ? 'text-success' : 'text-danger'))
const signalType = signal => ({ 买入: 'danger', 卖出: 'success', 持有: 'info' }[signal] || 'info')
const signalStatusLabel = row => {
  const status = row.status
  if (status === 'pending') return '待执行'
  if (status === 'executed') return row.signal === '持有' ? '已处理' : '已成交'
  if (status === 'skipped') return '已跳过'
  if (status === 'expired') return '已过期'
  return status || '—'
}
const signalStatusType = status => ({ pending: 'warning', executed: 'success', skipped: 'info', expired: 'info' }[status] || 'info')
const heldCodeSet = computed(() => new Set(positions.value.filter(item => item.quantity > 0).map(item => item.code)))
const activeUniverseCodes = computed(() => new Set(universe.value.filter(item => item.status === 'active').map(item => item.code)))
const universeSourceLabels = { manual: '手工', pool: '原始池', scan_pick: '回测勾选', init: '账户初始化', api: '接口' }
const universeSourceLabel = row => universeSourceLabels[row.sourceType] || row.sourceType || '—'
const isHeld = code => heldCodeSet.value.has(code)

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
    const response = await getAccount(currentAccountName.value)
    account.value = response.data
  } catch {
    account.value = null
  }
}

async function loadAccounts() {
  try {
    const response = await listAccounts()
    accounts.value = response.data || []
    const names = accounts.value.map(item => item.accountName)
    if (!names.includes(currentAccountName.value)) {
      const firstActive = accounts.value.find(item => item.status === 'active')
      currentAccountName.value = firstActive ? firstActive.accountName : 'default'
    }
  } catch {
    accounts.value = []
  }
}

function handleAccountChange() {
  signalQuery.pageNum = 1
  orderQuery.pageNum = 1
  reloadAll()
  loadRealtimeQuotes()
}

function loadPositions() {
  if (!account.value) return
  positionsLoading.value = true
  getPositions(currentAccountName.value).then(response => {
    positions.value = response.data || []
  }).finally(() => {
    positionsLoading.value = false
  })
}

function loadUniverse() {
  if (!account.value) return
  universeLoading.value = true
  getUniverse(currentAccountName.value, universeStatus.value).then(response => {
    universe.value = response.data || []
  }).finally(() => {
    universeLoading.value = false
  })
}

async function handleRemoveUniverse(row) {
  try {
    await proxy.$modal.confirm(`确定将 ${row.code} ${row.name || ''} 移出标的池？移出后不再产生新信号，持仓不受影响。`)
  } catch {
    return
  }
  removingCode.value = row.code
  try {
    await removeFromUniverse({ accountName: currentAccountName.value, codes: [row.code] })
    proxy.$modal.msgSuccess('已移出标的池')
    loadUniverse()
  } catch (error) {
    const message = error?.message || (typeof error === 'string' ? error : '')
    if (message) proxy.$modal.msgError(message)
  } finally {
    removingCode.value = null
  }
}

function openUniverseAddDialog() {
  universeAddTab.value = 'pool'
  pickerPoolName.value = ''
  pickerRows.value = []
  pickerTotal.value = 0
  pickerSelection.value = []
  manualCodesText.value = ''
  pickerQuery.pageNum = 1
  universeAddVisible.value = true
  loadPoolNames()
}

function handlePickerPoolChange() {
  pickerQuery.pageNum = 1
  pickerSelection.value = []
  loadPickerRows()
}

function loadPickerRows() {
  if (!pickerPoolName.value) return
  pickerLoading.value = true
  listStockPool({ poolName: pickerPoolName.value, pageNum: pickerQuery.pageNum, pageSize: pickerQuery.pageSize }).then(response => {
    pickerRows.value = response.rows || []
    pickerTotal.value = response.total || 0
  }).finally(() => {
    pickerLoading.value = false
  })
}

function handlePickerSelectionChange(rows) {
  pickerSelection.value = rows
}

async function handleUniverseAdd() {
  let payload = null
  if (universeAddTab.value === 'pool') {
    if (!pickerPoolName.value) {
      proxy.$modal.msgWarning('请先选择股票池')
      return
    }
    const selectedCodes = pickerSelection.value.map(item => item.code)
    payload = { accountName: currentAccountName.value, poolName: pickerPoolName.value }
    if (selectedCodes.length) payload.poolCodes = selectedCodes
  } else {
    const codes = parseCodes(manualCodesText.value)
    if (!codes.length) {
      proxy.$modal.msgWarning('请输入有效的6位股票代码')
      return
    }
    payload = { accountName: currentAccountName.value, codes }
  }
  universeAddLoading.value = true
  try {
    const response = await addToUniverse(payload)
    const result = response.data || {}
    proxy.$modal.msgSuccess(`加入完成：新增 ${result.addedCount ?? 0} 只，跳过 ${result.skippedCount ?? 0} 只`)
    universeAddVisible.value = false
    loadUniverse()
  } catch (error) {
    const message = error?.message || (typeof error === 'string' ? error : '')
    if (message) proxy.$modal.msgError(message)
  } finally {
    universeAddLoading.value = false
  }
}

function openUniverseLogDrawer() {
  universeLogVisible.value = true
  universeLogQuery.pageNum = 1
  loadUniverseLogs()
}

function loadUniverseLogs() {
  universeLogLoading.value = true
  getUniverseLogs({ accountName: currentAccountName.value, pageNum: universeLogQuery.pageNum, pageSize: universeLogQuery.pageSize }).then(response => {
    universeLogs.value = response.rows || []
    universeLogTotal.value = response.total || 0
  }).finally(() => {
    universeLogLoading.value = false
  })
}

function loadSignals() {
  if (!account.value) return
  signalsLoading.value = true
  getSignals({ accountName: currentAccountName.value, pageNum: signalQuery.pageNum, pageSize: signalQuery.pageSize }).then(response => {
    signals.value = response.rows || []
    signalTotal.value = response.total || 0
  }).finally(() => {
    signalsLoading.value = false
  })
}

function loadOrders() {
  if (!account.value) return
  ordersLoading.value = true
  getOrders({ accountName: currentAccountName.value, pageNum: orderQuery.pageNum, pageSize: orderQuery.pageSize }).then(response => {
    orders.value = response.rows || []
    orderTotal.value = response.total || 0
  }).finally(() => {
    ordersLoading.value = false
  })
}

function loadSnapshot() {
  if (!account.value) return
  chartLoading.value = true
  getSnapshot({ accountName: currentAccountName.value }).then(response => {
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

function loadRealtimeQuotes() {
  if (!account.value) return
  quotesLoading.value = true
  getRealtimeQuotes(currentAccountName.value).then(response => {
    realtimeQuotes.value = response.data || []
  }).finally(() => {
    quotesLoading.value = false
  })
}

async function handleRunSignal() {
  signalLoading.value = true
  try {
    await runSignal(currentAccountName.value)
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
    await runExecute(currentAccountName.value)
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

async function handleRunRealtime() {
  realtimeLoading.value = true
  try {
    await runRealtime(currentAccountName.value)
    proxy.$modal.msgSuccess('实时轮循执行完成')
    await loadAccount()
    signalQuery.pageNum = 1
    orderQuery.pageNum = 1
    loadUniverse()
    loadPositions()
    loadSignals()
    loadOrders()
    loadSnapshot()
  } finally {
    realtimeLoading.value = false
  }
}

async function handleRecallSignal(row) {
  recallLoadingId.value = row.id
  try {
    await recallSignalNotification(row.id)
    proxy.$modal.msgSuccess('飞书通知已撤回')
  } finally {
    recallLoadingId.value = null
  }
}
async function handleRunDailySync() {
  syncLoading.value = true
  try {
    // 同步全部 active 账户的标的池（后端合并去重）；不传 accountName 即全量同步
    await runDailySync()
    proxy.$modal.msgSuccess('标的池日线同步完成')
  } finally {
    syncLoading.value = false
  }
}

async function loadPoolNames() {
  if (poolNames.value.length) return
  poolLoading.value = true
  try {
    poolNames.value = (await listStockPoolNames()).data || []
  } finally {
    poolLoading.value = false
  }
}

function handlePoolDropdown(visible) {
  if (visible) loadPoolNames()
}

function openInitDialog() {
  initMode.value = 'reset'
  Object.assign(initForm, { accountName: currentAccountName.value, strategyName: account.value?.strategyName || '', initialCash: 1000000, codesText: '', poolName: '' })
  initVisible.value = true
}

function openManageDialog() {
  manageRows.value = accounts.value.map(item => ({ ...item }))
  manageVisible.value = true
}

function saveManageRow(row) {
  manageSavingId.value = row.id
  updateAccount(row.id, { strategyName: row.strategyName, status: row.status }).then(() => {
    proxy.$modal.msgSuccess('账户已更新')
    loadAccounts().then(() => {
      manageRows.value = accounts.value.map(item => ({ ...item }))
      reloadAll()
    })
  }).finally(() => {
    manageSavingId.value = null
  })
}

function handleDeleteAccount(row) {
  proxy.$modal
    .confirm(
      '删除账户 ' + row.accountName + ' 将同时清空其标的池、信号、持仓、成交与净值历史，且不可恢复。确定删除？'
    )
    .then(() => deleteAccount(row.id))
    .catch(error => {
      const message = error?.message || (typeof error === 'string' ? error : '')
      if (!message || !message.includes('持仓')) {
        return Promise.reject(error)
      }
      return proxy.$modal.confirm(
        '该账户仍有持仓。强制删除将丢弃全部持仓与交易记录，确定继续？'
      ).then(() => deleteAccount(row.id, true))
    })
    .then(() => {
      proxy.$modal.msgSuccess('账户已删除')
      if (currentAccountName.value === row.accountName) {
        const rest = accounts.value.filter(item => item.id !== row.id)
        const next = rest.find(item => item.status === 'active')
        currentAccountName.value = next ? next.accountName : 'default'
      }
      signalQuery.pageNum = 1
      orderQuery.pageNum = 1
      loadAccounts().then(() => {
        manageRows.value = accounts.value.map(item => ({ ...item }))
        reloadAll()
      })
    })
    .catch(() => {})
}

function openCreateDialog() {
  initMode.value = 'create'
  Object.assign(initForm, { accountName: '', strategyName: '', initialCash: 1000000, codesText: '', poolName: '' })
  initVisible.value = true
}

function handleInit() {
  initFormRef.value?.validate(valid => {
    if (!valid) return
    const codes = parseCodes(initForm.codesText)
    initLoading.value = true
    initAccount({
      accountName: initForm.accountName,
      strategyName: initForm.strategyName,
      initialCash: initForm.initialCash,
      ...(codes.length ? { codes } : {}),
      ...(initForm.poolName ? { poolName: initForm.poolName } : {})
    }).then(() => {
      proxy.$modal.msgSuccess(initMode.value === 'create' ? '模拟账户创建完成' : '模拟账户初始化完成')
      initVisible.value = false
      currentAccountName.value = initForm.accountName
      loadAccounts().then(() => {
        signalQuery.pageNum = 1
        orderQuery.pageNum = 1
        reloadAll()
      })
    }).finally(() => {
      initLoading.value = false
    })
  })
}

onBeforeUnmount(() => {
  chart?.dispose()
  if (refreshTimer) clearInterval(refreshTimer)
  if (quotesTimer) clearInterval(quotesTimer)
})
loadStrategies()
loadAccounts().then(() => {
  reloadAll()
})
refreshTimer = setInterval(reloadAll, 60000)
loadRealtimeQuotes()
quotesTimer = setInterval(loadRealtimeQuotes, 30000)
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
.account-select {
  width: 220px;
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
.ml8 {
  margin-left: 8px;
}
.mt8 {
  margin-top: 8px;
}
.picker-tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>