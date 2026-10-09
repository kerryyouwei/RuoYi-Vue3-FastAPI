import request from '@/utils/request'

/** 提交股票池批量回测 */
export function runScan(data) {
  return request({
    url: '/stock/scan/run',
    method: 'post',
    data,
    timeout: 120000
  })
}

/** 查询批量回测批次状态 */
export function getScan(batchId) {
  return request({
    url: `/stock/scan/${batchId}`,
    method: 'get'
  })
}

/** 分页查询批量回测结果 */
export function getScanItems(batchId, params) {
  return request({
    url: `/stock/scan/${batchId}/items`,
    method: 'get',
    params
  })
}

/** 勾选加入模拟盘标的池 */
export function pickToPaper(data) {
  return request({
    url: '/stock/scan/pick',
    method: 'post',
    data
  })
}