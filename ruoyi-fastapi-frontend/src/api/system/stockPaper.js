import request from '@/utils/request'

/** 查询全部模拟盘账户 */
export function listAccounts() {
  return request({
    url: '/stock/paper/accounts',
    method: 'get'
  })
}

/** 新建模拟盘账户 */
export function createAccount(data) {
  return request({
    url: '/stock/paper/account/create',
    method: 'post',
    data
  })
}

/** 更新模拟盘账户（策略/启停） */
export function updateAccount(accountId, data) {
  return request({
    url: '/stock/paper/account/' + accountId,
    method: 'put',
    data
  })
}

/** 删除模拟盘账户（force=true 时连同持仓一并删除） */
export function deleteAccount(accountId, force = false) {
  return request({
    url: '/stock/paper/account/' + accountId,
    method: 'delete',
    params: force ? { force: true } : {}
  })
}

/** 初始化模拟盘账户 */
export function initAccount(data) {
  return request({
    url: '/stock/paper/account/init',
    method: 'post',
    data
  })
}

/** 查询模拟盘账户概览 */
export function getAccount(accountName = 'default') {
  return request({
    url: '/stock/paper/account',
    method: 'get',
    params: { accountName }
  })
}

/** 查询模拟盘标的池（status: active/inactive/all，默认 active） */
export function getUniverse(accountName = 'default', status = 'active') {
  return request({
    url: '/stock/paper/universe',
    method: 'get',
    params: { accountName, status }
  })
}

/** 动态加入标的池（codes 直接加入 / poolName 整池 / poolName + poolCodes 从池中挑选） */
export function addToUniverse(data) {
  return request({
    url: '/stock/paper/universe/add',
    method: 'post',
    data
  })
}

/** 动态移出标的池（持仓中的标的会被整体拒绝） */
export function removeFromUniverse(data) {
  return request({
    url: '/stock/paper/universe/remove',
    method: 'post',
    data
  })
}

/** 分页查询标的池变更日志 */
export function getUniverseLogs(params) {
  return request({
    url: '/stock/paper/universe/log',
    method: 'get',
    params
  })
}

/** 查询模拟盘持仓 */
export function getPositions(accountName = 'default') {
  return request({
    url: '/stock/paper/positions',
    method: 'get',
    params: { accountName }
  })
}

/** 分页查询交易信号 */
export function getSignals(params) {
  return request({
    url: '/stock/paper/signals',
    method: 'get',
    params
  })
}

/** 分页查询成交/跳过记录 */
export function getOrders(params) {
  return request({
    url: '/stock/paper/orders',
    method: 'get',
    params
  })
}

/** 查询模拟盘净值快照 */
export function getSnapshot(params) {
  return request({
    url: '/stock/paper/snapshot',
    method: 'get',
    params
  })
}

/** 手动触发收盘信号计算（accountName 为空时处理全部账户） */
export function runSignal(accountName) {
  return request({
    url: '/stock/paper/signal/run',
    method: 'post',
    timeout: 120000,
    params: accountName ? { accountName } : {}
  })
}

/** 手动触发开盘撮合（accountName 为空时处理全部账户） */
export function runExecute(accountName) {
  return request({
    url: '/stock/paper/execute/run',
    method: 'post',
    timeout: 120000,
    params: accountName ? { accountName } : {}
  })
}

/** 手动触发实时轮循（accountName 为空时处理全部账户） */
export function runRealtime(accountName) {
  return request({
    url: '/stock/paper/realtime/run',
    method: 'post',
    timeout: 120000,
    params: accountName ? { accountName } : {}
  })
}

/** 手动触发标的池日线同步（accountName 为空时合并全部账户去重同步） */
export function runDailySync(accountName) {
  return request({
    url: '/stock/paper/daily-sync/run',
    method: 'post',
    timeout: 300000,
    params: accountName ? { accountName } : {}
  })
}

/** 查询标的池实时行情 */
export function getRealtimeQuotes(accountName = 'default') {
  return request({
    url: '/stock/paper/realtime-quotes',
    method: 'get',
    params: { accountName }
  })
}
/** 撤回交易信号飞书通知 */
export function recallSignalNotification(signalId, reason = '信号作废，通知已撤回') {
  return request({
    url: `/stock/paper/signals/${signalId}/recall`,
    method: 'post',
    data: { reason }
  })
}
