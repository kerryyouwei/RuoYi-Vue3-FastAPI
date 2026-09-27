import request from '@/utils/request'

export const listStrategies = (params) => request({ url: '/stock/strategy/list', method: 'get', params })
export const getStrategy = (strategyName) => request({ url: `/stock/strategy/${strategyName}`, method: 'get' })
export const runStrategy = (data) => request({ url: '/stock/strategy/run', method: 'post', data })
export const getRunStatus = (runId) => request({ url: `/stock/strategy/run/${runId}`, method: 'get' })
export const getRunDetail = (runId) => request({ url: `/stock/strategy/run/${runId}/detail`, method: 'get' })
export const getStrategyHistory = (strategyName, params) => request({ url: `/stock/strategy/${strategyName}/history`, method: 'get', params })
