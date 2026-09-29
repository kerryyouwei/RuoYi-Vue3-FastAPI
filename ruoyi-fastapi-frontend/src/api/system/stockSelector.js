import request from '@/utils/request'

/** 问财智能选股查询 */
export function searchAStock(query) {
  return request({
    url: '/stock/selector/search',
    method: 'get',
    params: query,
    timeout: 120000
  })
}

/** 批量加入股票池 */
export function addStockPool(data) {
  return request({
    url: '/stock/selector/pool/add',
    method: 'post',
    data
  })
}

/** 分页查询股票池 */
export function listStockPool(query) {
  return request({
    url: '/stock/selector/pool/list',
    method: 'get',
    params: query
  })
}

/** 查询股票池名称列表 */
export function listStockPoolNames() {
  return request({
    url: '/stock/selector/pool/names',
    method: 'get'
  })
}

/** 删除股票池记录 */
export function removeStockPool(itemId) {
  return request({
    url: `/stock/selector/pool/${itemId}`,
    method: 'delete'
  })
}
