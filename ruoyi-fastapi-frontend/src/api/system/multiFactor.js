import request from '@/utils/request'

/** 触发多因子计算 */
export function calculateMultiFactor() {
  return request({
    url: '/stock/multi-factor/calculate',
    method: 'post',
    timeout: 600000
  })
}

/** 查询多因子选股结果 */
export function listMultiFactorResults(query) {
  return request({
    url: '/stock/multi-factor/list',
    method: 'get',
    params: query
  })
}

/** 查询最新批次信息 */
export function getLatestBatch() {
  return request({
    url: '/stock/multi-factor/batch/latest',
    method: 'get'
  })
}

/** 查询因子权重配置 */
export function getFactorWeights() {
  return request({
    url: '/stock/multi-factor/weights',
    method: 'get'
  })
}

/** 入选股票加入股票池 */
export function addMultiFactorToPool(data) {
  return request({
    url: '/stock/multi-factor/pool/add',
    method: 'post',
    data
  })
}

/** 查询股票池名称列表（复用智能选股的接口） */
export function listStockPoolNames() {
  return request({
    url: '/stock/selector/pool/names',
    method: 'get'
  })
}
