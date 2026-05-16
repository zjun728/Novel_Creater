/**
 * 自动备份系统
 *
 * 通过后端 API 导出全量 JSON 到本地文件
 * 备份状态存储在 localStorage 中
 */
import { api } from '@/api/db/client'

const STATUS_KEY = 'novel_creator_backup_status'
const DEFAULT_INTERVAL_MINUTES = 30

let autoTimer = null
let backupRunning = false

export function getBackupStatus() {
  try {
    const raw = localStorage.getItem(STATUS_KEY)
    if (!raw) return { lastBackup: null, count: 0 }
    return JSON.parse(raw)
  } catch {
    return { lastBackup: null, count: 0 }
  }
}

function updateStatus() {
  const status = getBackupStatus()
  status.lastBackup = Date.now()
  status.count = (status.count || 0) + 1
  localStorage.setItem(STATUS_KEY, JSON.stringify(status))
  return status
}

export async function exportFullDatabase() {
  const data = await api.exportFull()
  return JSON.stringify(data, null, 2)
}

export async function downloadBackup() {
  if (backupRunning) {
    console.warn('[备份] 已有备份任务进行中，跳过')
    return null
  }
  backupRunning = true
  try {
    const json = await exportFullDatabase()
    const status = updateStatus()
    const dateStr = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `NovelCreator_全量备份_${dateStr}_#${status.count}.json`

    const blob = new Blob([json], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)

    return { filename, status }
  } finally {
    backupRunning = false
  }
}

export function startAutoBackup(intervalMinutes) {
  stopAutoBackup()
  const ms = (intervalMinutes || DEFAULT_INTERVAL_MINUTES) * 60 * 1000

  autoTimer = setInterval(async () => {
    try {
      await downloadBackup()
      console.log('[自动备份] 完成')
    } catch (e) {
      console.warn('[自动备份] 失败:', e.message)
    }
  }, ms)

  console.log(`[自动备份] 已启动，间隔 ${intervalMinutes || DEFAULT_INTERVAL_MINUTES} 分钟`)
  return autoTimer
}

export function stopAutoBackup() {
  if (autoTimer) {
    clearInterval(autoTimer)
    autoTimer = null
  }
}

export function timeSinceBackup() {
  const status = getBackupStatus()
  if (!status.lastBackup) return '从未备份'

  const diff = Date.now() - status.lastBackup
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (hours < 24) return `${hours} 小时前`
  return `${days} 天前`
}

export function needsReminder() {
  const status = getBackupStatus()
  if (!status.lastBackup) return true
  return Date.now() - status.lastBackup > 7 * 24 * 60 * 60 * 1000
}
