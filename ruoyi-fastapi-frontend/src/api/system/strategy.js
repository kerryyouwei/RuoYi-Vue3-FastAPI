import request from '@/utils/request'

export const listStrategies = (params) => request({ url: '/stock/strategy/list', method: 'get', params })
export const getStrategy = (strategyName) => request({ url: `/stock/strategy/${strategyName}`, method: 'get' })
export const runStrategy = (data) => request({ url: '/stock/strategy/run', method: 'post', data })
export const getRunStatus = (runId) => request({ url: `/stock/strategy/run/${runId}`, method: 'get' })
export const getRunDetail = (runId) => request({ url: `/stock/strategy/run/${runId}/detail`, method: 'get' })
export const getRunTrades = (runId, params = {}) => request({ url: `/stock/strategy/run/${runId}/trades`, method: 'get', params: { tradePageNum: params.pageNum ?? 1, tradePageSize: params.pageSize ?? 50 } })
export const getStrategyHistory = (strategyName, params) => request({ url: `/stock/strategy/${strategyName}/history`, method: 'get', params })
export const validateStrategy = (data) => request({ url: '/stock/strategy/validate', method: 'post', data })
export const getValidationStatus = (validationId) => request({ url: `/stock/strategy/validation/${validationId}`, method: 'get' })
export const listValidations = (params) => request({ url: '/stock/strategy/validation', method: 'get', params })
