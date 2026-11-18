<template>
  <section class="page" data-module="storage">
    <header class="page-head">
      <div>
        <h2>存储落地管理</h2>
        <p class="page-desc">管理采集结果持久化的存储类型、分区和生命周期。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记存储配置</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出存储落地清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无存储落地数据，可先登记存储配置</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记存储配置</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <section class="sub-section">
      <header class="sub-head">
        <h3>去重落地清单</h3>
        <span class="sub-desc">消费重复去重的去重明细数据集，只落地去重后的保留项；同一数据集不会生成重复结果。</span>
      </header>
      <form class="filter-bar" @submit.prevent="reloadManifest">
        <label class="filter-item">
          <span>数据集编号</span>
          <select v-model="manifestDatasetNo" data-testid="manifest-dataset" @change="reloadManifest">
            <option value="">全部数据集</option>
            <option v-for="dataset in datasetOptions" :key="String(dataset.数据集编号)" :value="dataset.数据集编号">
              {{ dataset.数据集编号 }} · {{ dataset.批次编号 }} · {{ dataset.策略版本 }}
            </option>
          </select>
        </label>
        <label class="filter-item">
          <span>配置编号</span>
          <input v-model="manifestStorageNo" data-testid="manifest-storage" placeholder="选择落地配置" />
        </label>
        <button class="btn" data-testid="manifest-query" type="submit">查看清单</button>
        <button class="btn primary" data-testid="manifest-build" type="button" @click="buildManifest">
          生成去重落地清单
        </button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th>落地编号</th>
            <th>配置编号</th>
            <th>数据集编号</th>
            <th>批次编号</th>
            <th>策略编号</th>
            <th>策略版本</th>
            <th>业务键</th>
            <th>记录编号</th>
            <th>记录摘要</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in manifestRows"
            :key="String(item.id)"
            :data-testid="`manifest-row-${item.落地编号}`"
          >
            <td>{{ item.落地编号 }}</td>
            <td>{{ item.配置编号 || '—' }}</td>
            <td>{{ item.数据集编号 }}</td>
            <td>{{ item.批次编号 }}</td>
            <td>{{ item.策略编号 }}</td>
            <td class="version-cell">{{ item.策略版本 }}</td>
            <td>{{ item.业务键 }}</td>
            <td>{{ item.记录编号 }}</td>
            <td>{{ item.记录摘要 || '—' }}</td>
          </tr>
          <tr v-if="!manifestRows.length">
            <td colspan="9" class="empty-state">暂无去重落地清单，可先在重复去重生成去重明细数据集</td>
          </tr>
        </tbody>
      </table>
      <p v-if="manifestMessage" class="hint-text" data-testid="manifest-message">{{ manifestMessage }}</p>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条存储落地记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type ManifestRow = {
  id?: number
  落地编号: string
  配置编号: string
  数据集编号: string
  批次编号: string
  策略编号: string
  策略版本: string
  业务键: string
  记录编号: string
  记录摘要: string
}

const ENDPOINT = '/api/storage'
const columns = ["配置编号", "存储类型", "连接信息", "分区策略", "压缩格式", "保存天数", "备份副本", "清理策略"]
const actions = ["提交校验", "启用配置", "停用配置"]
const statuses = ["草稿", "待校验", "已启用", "已停用"]
const metricNames = ["存储配置总数", "待校验存储配置", "已启用存储配置"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'storage.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('存储落地动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '存储落地操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('存储配置列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '存储落地列表读取失败'
  }
  await Promise.all([reloadManifest(), reloadDatasetOptions()])
}

const manifestRows = ref<ManifestRow[]>([])
const manifestDatasetNo = ref('')
const manifestStorageNo = ref('')
const manifestMessage = ref('')
const datasetOptions = ref<Row[]>([])

async function reloadDatasetOptions() {
  try {
    const payload = await fetchJson<{ items: Row[] }>('/api/dedup/datasets?size=200')
    datasetOptions.value = payload.items ?? []
  } catch {
    datasetOptions.value = []
  }
}

async function reloadManifest() {
  const params = new URLSearchParams()
  if (manifestDatasetNo.value) params.set('dataset_no', manifestDatasetNo.value)
  if (manifestStorageNo.value) params.set('storage_no', manifestStorageNo.value)
  try {
    const payload = await fetchJson<{ items: ManifestRow[] }>(`${ENDPOINT}/manifest?${params.toString()}`)
    manifestRows.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '去重落地清单读取失败'
  }
}

async function buildManifest() {
  errorMessage.value = ''
  manifestMessage.value = ''
  if (!manifestDatasetNo.value) {
    errorMessage.value = '请先选择去重明细数据集，再生成去重落地清单'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/manifest`, {
      method: 'POST',
      body: JSON.stringify({
        数据集编号: manifestDatasetNo.value,
        配置编号: manifestStorageNo.value,
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '生成去重落地清单失败')
    manifestMessage.value = payload.message
    await reloadManifest()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '生成去重落地清单失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.sub-section { margin-top: 24px; }
.sub-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; }
.sub-head h3 { margin: 0; font-size: 15px; }
.sub-desc { color: var(--muted); font-size: 12px; }
.version-cell { font-family: monospace; font-size: 11px; }
.hint-text { color: #1f6feb; font-size: 12px; }
.filter-item select { border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; }
.version-cell { font-family: monospace; font-size: 11px; }
</style>
