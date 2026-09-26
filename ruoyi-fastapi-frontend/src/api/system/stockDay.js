import request from '@/utils/request'

// 查询股票日线数据
export function listStockDay(query) {
  return request({
    url: '/stock/day/list',
    method: 'get',
    params: query
  })
}

// 从Baostock获取并导入股票日线数据
export function importStockDay(query) {
  return request({
    url: '/stock/day/import',
    method: 'post',
    params: query,
    timeout: 120000
  })
}
