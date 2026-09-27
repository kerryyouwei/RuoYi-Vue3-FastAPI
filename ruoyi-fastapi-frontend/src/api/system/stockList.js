import request from '@/utils/request'

// 查询A股股票列表
export function listStockList(query) {
  return request({
    url: '/stock/list/list',
    method: 'get',
    params: query
  })
}

// 从Baostock获取并导入A股股票列表
export function importStockList() {
  return request({
    url: '/stock/list/import',
    method: 'post',
    timeout: 120000
  })
}
