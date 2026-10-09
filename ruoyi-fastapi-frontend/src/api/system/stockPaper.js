import request from '@/utils/request'

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

/** 查询模拟盘标的池 */
export function getUniverse(accountName = 'default') {
  return request({
    url: '/stock/paper/universe',
    method: 'get',
    params: { accountName }
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

/** 手动触发收盘信号计算 */
export function runSignal() {
  return request({
    url: '/stock/paper/signal/run',
    method: 'post',
    timeout: 120000
  })
}

/** 手动触发开盘撮合 */
export function runExecute() {
  return request({
    url: '/stock/paper/execute/run',
    method: 'post',
    timeout: 120000
  })
}