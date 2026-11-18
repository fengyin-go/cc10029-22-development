<template>
  <section class="page" data-module="dedup">
    <header class="page-head">
      <div>
        <h2>重复去重管理</h2>
        <p class="page-desc">配置采集数据的去重算法、对比窗口和保留策略，并生成带策略依据的去重明细数据集。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记去重策略</button>
        <button class="btn" data-testid="open-generate" type="button" @click="openGenerate()">生成去重明细数据集</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出重复去重清单</button>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无重复去重数据，可先登记去重策略</td>
        </tr>
      </tbody>
    </table>

    <!-- 原始采集批次 -->
    <section class="sub-section">
      <header class="sub-head">
        <h3>原始采集批次</h3>
        <span class="sub-desc">去重前的采集批次与原始记录，刷新后仍保留同一批次编号。</span>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>批次编号</th>
            <th>关联任务</th>
            <th>来源站点</th>
            <th>采集时间</th>
            <th>状态</th>
            <th>原始记录数</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in rawBatches" :key="batch.批次编号" :data-testid="`batch-${batch.批次编号}`">
            <td>{{ batch.批次编号 }}</td>
            <td>{{ batch.关联任务 ?? '—' }}</td>
            <td>{{ batch.来源站点 ?? '—' }}</td>
            <td>{{ batch.采集时间 ?? '—' }}</td>
            <td>{{ batch.状态 ?? '—' }}</td>
            <td>{{ (batch.原始记录 ?? []).length }}</td>
            <td class="row-actions">
              <button class="link" type="button" :data-testid="`batch-view-${batch.批次编号}`" @click="viewBatch(batch)">
                查看原始记录
              </button>
              <button class="link" type="button" :data-testid="`batch-generate-${batch.批次编号}`" @click="openGenerate(batch)">
                生成去重明细
              </button>
            </td>
          </tr>
          <tr v-if="!rawBatches.length">
            <td colspan="7" class="empty-state">暂无原始采集批次</td>
          </tr>
        </tbody>
      </table>
      <div v-if="activeBatch" class="evidence-panel" data-testid="raw-detail">
        <h4>批次 {{ activeBatch.批次编号 }} 的原始记录</h4>
        <table class="data-table compact">
          <thead>
            <tr><th>记录编号</th><th>业务键</th><th>内容摘要</th><th>相似度</th><th>采集时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="record in activeBatch.原始记录 ?? []" :key="record.记录编号">
              <td>{{ record.记录编号 }}</td>
              <td>{{ record[activeBatchKeyColumn] ?? '—' }}</td>
              <td>{{ record.内容摘要 ?? '—' }}</td>
              <td>{{ record.相似度 ?? '—' }}</td>
              <td>{{ record.采集时间 ?? record.更新时间 ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 去重明细数据集 -->
    <section class="sub-section">
      <header class="sub-head">
        <h3>去重明细数据集</h3>
        <span class="sub-desc">业务键、相似阈值、保留顺序与策略版本同时写入；同一批次只保留一份已确认版本。</span>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th>数据集编号</th>
            <th>批次编号</th>
            <th>策略编号</th>
            <th>业务键列</th>
            <th>相似阈值</th>
            <th>保留顺序</th>
            <th>策略版本</th>
            <th>保留</th>
            <th>重复</th>
            <th>拒绝</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="dataset in datasets"
            :key="String(dataset.数据集编号)"
            :data-testid="`dataset-${dataset.数据集编号}`"
            :data-status="String(dataset.状态)"
          >
            <td>{{ dataset.数据集编号 }}</td>
            <td>{{ dataset.批次编号 }}</td>
            <td>{{ dataset.策略编号 }}</td>
            <td>{{ dataset.业务键列 }}</td>
            <td>{{ dataset.相似阈值 }}</td>
            <td>{{ dataset.保留顺序 }}</td>
            <td class="version-cell">{{ dataset.策略版本 }}</td>
            <td>{{ dataset.保留数量 }}</td>
            <td>{{ dataset.重复数量 }}</td>
            <td>{{ dataset.拒绝数量 }}</td>
            <td>{{ dataset.状态 }}</td>
            <td class="row-actions">
              <button class="link" type="button" :data-testid="`dataset-view-${dataset.数据集编号}`" @click="viewDataset(dataset)">
                查看明细
              </button>
            </td>
          </tr>
          <tr v-if="!datasets.length">
            <td colspan="12" class="empty-state">暂无去重明细数据集，可从原始采集批次生成</td>
          </tr>
        </tbody>
      </table>

      <div v-if="activeDataset" class="evidence-panel" data-testid="dataset-detail">
        <h4>
          数据集 {{ activeDataset.dataset.数据集编号 }} · 策略版本
          <span data-testid="dataset-version">{{ activeDataset.dataset.策略版本 }}</span>
        </h4>
        <p class="sub-desc">
          批次 {{ activeDataset.dataset.批次编号 }} · 业务键 {{ activeDataset.dataset.业务键列 }} ·
          相似阈值 {{ activeDataset.dataset.相似阈值 }} · 保留顺序 {{ activeDataset.dataset.保留顺序 }}
        </p>

        <h5>正式去重明细（{{ activeDataset.details.length }}）</h5>
        <table class="data-table compact">
          <thead>
            <tr><th>记录编号</th><th>业务键</th><th>记录摘要</th><th>相似度</th><th>结论</th><th>保留顺序依据</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="detail in activeDataset.details"
              :key="String(detail.记录编号)"
              :data-testid="`detail-${detail.记录编号}`"
              :data-conclusion="detail.处理结论"
            >
              <td>{{ detail.记录编号 }}</td>
              <td>{{ detail.业务键 }}</td>
              <td>{{ detail.记录摘要 ?? '—' }}</td>
              <td>{{ detail.相似度 }}</td>
              <td>{{ detail.处理结论 }}</td>
              <td>{{ detail.保留顺序依据 }}</td>
            </tr>
          </tbody>
        </table>

        <h5>重复证据（{{ activeDataset.evidence.length }}）</h5>
        <table class="data-table compact">
          <thead>
            <tr><th>保留记录</th><th>重复记录</th><th>业务键</th><th>相似度</th><th>相似阈值</th><th>证据说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="evidence in activeDataset.evidence" :key="`${evidence.保留记录编号}-${evidence.重复记录编号}`">
              <td>{{ evidence.保留记录编号 }}</td>
              <td>{{ evidence.重复记录编号 }}</td>
              <td>{{ evidence.业务键 }}</td>
              <td>{{ evidence.相似度 }}</td>
              <td>{{ evidence.相似阈值 }}</td>
              <td>{{ evidence.证据说明 }}</td>
            </tr>
            <tr v-if="!activeDataset.evidence.length">
              <td colspan="6" class="empty-state">该数据集没有重复证据</td>
            </tr>
          </tbody>
        </table>

        <h5>未进入正式明细的记录（{{ activeDataset.rejections.length }}）</h5>
        <table class="data-table compact">
          <thead><tr><th>业务键</th><th>记录编号</th><th>原因</th></tr></thead>
          <tbody>
            <tr v-for="(rejection, index) in activeDataset.rejections" :key="`${rejection.记录编号}-${index}`">
              <td>{{ rejection.业务键 || '—' }}</td>
              <td>{{ rejection.记录编号 || '—' }}</td>
              <td>{{ rejection.原因 }}</td>
            </tr>
            <tr v-if="!activeDataset.rejections.length">
              <td colspan="3" class="empty-state">没有记录被拒绝</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记去重策略</h3>
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

    <div v-if="showGenerate" class="modal-backdrop" data-testid="generate-modal">
      <form class="modal" @submit.prevent="submitGenerate">
        <h3>生成去重明细数据集</h3>
        <p class="sub-desc">按去重策略把原始采集批次写入去重明细，无法解释保留顺序的记录不会进入正式明细。</p>
        <label class="create-field">
          <span>策略编号</span>
          <select v-model="generateValues.策略编号" data-testid="generate-策略编号" required>
            <option value="" disabled>请选择去重策略</option>
            <option v-for="policy in policyOptions" :key="policy" :value="policy">{{ policy }}</option>
          </select>
        </label>
        <label class="create-field">
          <span>批次编号</span>
          <select v-model="generateValues.批次编号" data-testid="generate-批次编号" required>
            <option value="" disabled>请选择原始采集批次</option>
            <option v-for="batch in rawBatches" :key="batch.批次编号" :value="batch.批次编号">
              {{ batch.批次编号 }}
            </option>
          </select>
        </label>
        <label class="create-field">
          <span>相似阈值（留空取策略配置）</span>
          <input v-model="generateValues.相似阈值" data-testid="generate-相似阈值" placeholder="例如 0.92" />
        </label>
        <label class="create-field">
          <span>保留顺序（留空取策略配置）</span>
          <input v-model="generateValues.保留顺序" data-testid="generate-保留顺序" placeholder="例如 更新时间降序" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showGenerate = false">取消</button>
          <button class="btn primary" data-testid="submit-generate" type="submit" :disabled="generating">
            {{ generating ? '生成中…' : '确认生成' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条重复去重记录 · {{ datasets.length }} 个去重明细数据集</span>
      <span v-if="message" class="hint-text" data-testid="dedup-message">{{ message }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type RawBatch = {
  批次编号: string
  关联任务?: string
  来源站点?: string
  采集时间?: string
  状态?: string
  原始记录?: Record<string, string>[]
  keyColumn?: string
}
type DatasetBundle = {
  dataset: Row
  details: Row[]
  evidence: Row[]
  rejections: Row[]
}

const ENDPOINT = '/api/dedup'
const columns = ["策略编号", "业务键列", "去重算法", "对比窗口", "相似阈值", "保留顺序", "增量模式", "生效批次"]
const actions = ["提交校验", "启用配置", "停用配置"]
const statuses = ["草稿", "待校验", "已启用", "已停用"]
const metricNames = ["去重策略总数", "待校验去重策略", "已启用去重策略"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const message = ref('')
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

const rawBatches = ref<RawBatch[]>([])
const activeBatch = ref<RawBatch | null>(null)
const datasets = ref<Row[]>([])
const activeDataset = ref<DatasetBundle | null>(null)
const showGenerate = ref(false)
const generating = ref(false)
const generateValues = ref<Record<string, string>>({})
const policyOptions = computed(() => rows.value.map((row) => String(row.策略编号)).filter(Boolean))
const activeBatchKeyColumn = computed(() => String(activeBatch.value?.keyColumn ?? '商品链接'))

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
    link.download = 'dedup.csv'
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
      throw new Error('重复去重动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重复去重操作失败'
  }
}

function viewBatch(batch: RawBatch) {
  const selected = generateValues.value.策略编号
  const policy = rows.value.find((row) => row.策略编号 === selected) ?? rows.value[0]
  activeBatch.value = {
    ...batch,
    keyColumn: String(policy?.业务键列 ?? '商品链接'),
  }
}

function openGenerate(batch?: RawBatch) {
  generateValues.value = {
    策略编号: String(rows.value[0]?.策略编号 ?? ''),
    批次编号: batch?.批次编号 ?? String(rawBatches.value[0]?.批次编号 ?? ''),
    相似阈值: '',
    保留顺序: '',
  }
  errorMessage.value = ''
  message.value = ''
  showGenerate.value = true
}

async function submitGenerate() {
  generating.value = true
  errorMessage.value = ''
  message.value = ''
  try {
    const payload: Record<string, string> = {
      策略编号: generateValues.value.策略编号,
      批次编号: generateValues.value.批次编号,
    }
    if (generateValues.value.相似阈值) payload.相似阈值 = generateValues.value.相似阈值
    if (generateValues.value.保留顺序) payload.保留顺序 = generateValues.value.保留顺序
    const response = await request(`${ENDPOINT}/datasets`, {
      method: 'POST', body: JSON.stringify(payload),
    })
    const result = await response.json()
    if (!response.ok || !result.ok) throw new Error(result.message || '生成去重明细数据集失败')
    message.value = result.message
    showGenerate.value = false
    await reload()
    const datasetNo = result.entry?.dataset?.数据集编号
    if (datasetNo) await viewDataset({ 数据集编号: datasetNo })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '生成去重明细数据集失败'
  } finally {
    generating.value = false
  }
}

async function viewDataset(dataset: Row) {
  errorMessage.value = ''
  try {
    const bundle = await fetchJson<DatasetBundle>(`${ENDPOINT}/datasets/${dataset.数据集编号}`)
    activeDataset.value = bundle
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '去重明细数据集读取失败'
  }
}

async function reloadRawBatches() {
  try {
    const payload = await fetchJson<{ items: RawBatch[] }>(`${ENDPOINT}/raw-batches?size=200`)
    rawBatches.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '原始采集批次读取失败'
  }
}

async function reloadDatasets() {
  try {
    const payload = await fetchJson<{ items: Row[] }>(`${ENDPOINT}/datasets?size=200`)
    datasets.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '去重明细数据集读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('去重策略列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重复去重列表读取失败'
  }
  await Promise.all([reloadRawBatches(), reloadDatasets()])
}

onMounted(reload)
</script>

<style scoped>
.sub-section { margin-top: 24px; }
.sub-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; }
.sub-head h3 { margin: 0; font-size: 15px; }
.sub-desc { color: var(--muted); font-size: 12px; }
.evidence-panel { margin-top: 10px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; background: #fafbfc; }
.evidence-panel h4 { margin: 0 0 8px; font-size: 14px; }
.evidence-panel h5 { margin: 14px 0 6px; font-size: 13px; color: var(--muted); }
.data-table.compact th, .data-table.compact td { padding: 6px 8px; font-size: 12px; }
.version-cell { font-family: monospace; font-size: 11px; }
.hint-text { color: #1f6feb; }
.create-field select { width: 100%; box-sizing: border-box; border: 1px solid var(--border); border-radius: 6px; padding: 8px; }
</style>
