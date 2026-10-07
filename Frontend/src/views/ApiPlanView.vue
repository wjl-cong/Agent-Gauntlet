<script setup>
/**
 * API 测试规划 —— 实时拉取焰哨 openapi（5 分钟缓存），按路径分组展示，
 * 并用任务注册表标注每个端点被哪些测试任务覆盖（未覆盖端点高亮提示）。
 */
import { computed, onMounted, ref } from 'vue'
import { getApis } from '@/api/client'

const data = ref(null)
const loading = ref(false)
const keyword = ref('')

onMounted(refresh)

async function refresh() {
  loading.value = true
  try {
    data.value = await getApis()
  } catch (e) {
    ElMessage.error('加载失败：' + e.message)
  } finally {
    loading.value = false
  }
}

const METHOD_COLOR = {
  GET: '#67c23a',
  POST: '#3b82f6',
  PUT: '#e6a23c',
  DELETE: '#f56c6c',
  PATCH: '#9fd8ff',
}

function groupOf(path) {
  const m = path.match(/^\/api\/v1\/([^/]+)/)
  return m ? m[1] : 'root'
}

const GROUP_NAME = {
  auth: '认证', agent: 'Agent 任务链', reports: '报告', rag: '知识问答',
  dashboard: '数据看板', query: '查询', vision: '视觉/语音', admin: '管理',
}

const groups = computed(() => {
  if (!data.value) return []
  const kw = keyword.value.trim().toLowerCase()
  const map = new Map()
  for (const a of data.value.apis) {
    if (kw && !(a.path.toLowerCase().includes(kw) || a.summary.toLowerCase().includes(kw))) continue
    const g = groupOf(a.path)
    if (!map.has(g)) map.set(g, { key: g, name: GROUP_NAME[g] || g, apis: [] })
    map.get(g).apis.push(a)
  }
  return [...map.values()]
})

function coverageOf(a) {
  return a.coverage || (a.covered_by.length ? 'direct' : 'out')
}

const stat = computed(() => {
  const apis = data.value?.apis || []
  const s = { direct: 0, indirect: 0, out: 0 }
  for (const a of apis) s[coverageOf(a)] = (s[coverageOf(a)] || 0) + 1
  return s
})
</script>

<template>
  <div class="api-page">
    <header class="page-head">
      <div>
        <h2 class="page-title metal-text">API 测试规划</h2>
        <p class="page-sub">
          被测对象：焰哨（{{ data?.base_url || 'http://127.0.0.1:8000' }}）
          <a :href="data?.docs_url" target="_blank" class="docs-link">打开官方 API 文档 ↗</a>
        </p>
      </div>
      <div class="head-right">
        <el-tag :type="data?.yanshao_online ? 'success' : 'danger'" effect="plain" size="small">
          {{ data?.yanshao_online ? '焰哨在线 · openapi 已同步' : '焰哨离线 · 仅注册表视图' }}
        </el-tag>
        <el-input v-model="keyword" placeholder="搜索路径或说明" clearable style="width: 200px" />
        <el-button :loading="loading" @click="refresh">刷新</el-button>
      </div>
    </header>

    <div class="stats glass-panel" v-if="data">
      <div class="stat">
        <span class="stat-num metal-text">{{ data.apis.length }}</span>
        <span class="stat-label">端点总数</span>
      </div>
      <div class="stat">
        <span class="stat-num metal-text">{{ stat.direct }}</span>
        <span class="stat-label">直接规划（注册表任务直接触达）</span>
      </div>
      <div class="stat">
        <span class="stat-num metal-text">{{ stat.indirect }}</span>
        <span class="stat-label">间接覆盖（评测链路自动经过）</span>
      </div>
      <div class="stat">
        <span class="stat-num metal-text">{{ stat.out }}</span>
        <span class="stat-label">范围外（非 Agent 主链能力）</span>
      </div>
    </div>

    <div class="groups">
      <section v-for="g in groups" :key="g.key" class="group glass-panel">
        <h3 class="group-name">{{ g.name }}<span class="group-count">{{ g.apis.length }}</span></h3>
        <div v-for="a in g.apis" :key="a.method + a.path" class="api-row" :class="{ indirect: coverageOf(a) === 'indirect', out: coverageOf(a) === 'out' }">
          <span class="method" :style="{ color: METHOD_COLOR[a.method] || '#8b98ad' }">{{ a.method || '—' }}</span>
          <code class="path">{{ a.path }}</code>
          <span class="summary">{{ a.summary }}</span>
          <div class="cover">
            <template v-if="coverageOf(a) === 'direct'">
              <el-tag
                v-for="t in a.covered_by"
                :key="t.id"
                size="small"
                effect="dark"
                :type="t.category === 'attack' ? 'danger' : t.category === 'chaos' ? 'warning' : 'success'"
              >
                {{ t.name }}
              </el-tag>
            </template>
            <el-tooltip v-else-if="coverageOf(a) === 'indirect'" :content="a.coverage_note || '评测链路自动经过'" placement="top">
              <el-tag size="small" type="info" effect="plain">间接覆盖</el-tag>
            </el-tooltip>
            <el-tooltip v-else :content="a.coverage_note || '非 Agent 主链能力，不在当前红队规划范围'" placement="top">
              <el-tag size="small" type="info" effect="plain" class="out-tag">范围外</el-tag>
            </el-tooltip>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.api-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
}

.page-title {
  font-size: 22px;
  margin: 0 0 4px;
}

.page-sub {
  margin: 0;
  font-size: 13px;
  color: var(--g-text-dim);
}

.docs-link {
  color: var(--g-accent);
  margin-left: 10px;
  text-decoration: none;
}

.docs-link:hover {
  text-decoration: underline;
}

.head-right {
  display: flex;
  gap: 10px;
  align-items: center;
}

.stats {
  display: flex;
  gap: 48px;
  padding: 16px 26px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-num {
  font-size: 26px;
  font-weight: 700;
}

.stat-label {
  font-size: 12px;
  color: var(--g-text-dim);
}

.groups {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-bottom: 6px;
}

.group {
  padding: 14px 18px;
}

.group-name {
  margin: 0 0 10px;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.group-count {
  font-size: 11px;
  color: var(--g-text-dim);
  border: 1px solid var(--g-border);
  border-radius: 999px;
  padding: 1px 8px;
}

.api-row {
  display: grid;
  grid-template-columns: 52px minmax(220px, 340px) 1fr auto;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid transparent;
  transition: background 0.2s ease;
}

.api-row:hover {
  background: var(--g-panel-strong);
}

.api-row.uncovered,
.api-row.out {
  opacity: 0.6;
}

.api-row.indirect {
  background: rgba(64, 158, 255, 0.05);
}

.api-row.indirect:hover {
  background: rgba(64, 158, 255, 0.09);
}

.api-row.out:hover {
  background: var(--g-panel-strong);
}

.out-tag {
  opacity: 0.8;
}

.method {
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.05em;
}

.path {
  font-size: 12px;
  color: #9fd8ff;
  overflow-wrap: anywhere;
}

.summary {
  font-size: 12.5px;
  color: var(--g-text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cover {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
</style>
