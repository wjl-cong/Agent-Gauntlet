<script setup>
/**
 * 测试历史 —— 每次 run 一条独立记录（不覆盖），点击查看逐用例判定详情。
 */
import { onMounted, ref } from 'vue'
import { mdRender } from '@/utils/md'
import { getRun, getRuns, deleteRun, gradeTag, verdictTag } from '@/api/client'

const runs = ref([])
const loading = ref(false)
const drawer = ref(false)
const detail = ref(null)
const detailLoading = ref(false)

onMounted(refresh)

async function refresh() {
  loading.value = true
  try {
    runs.value = (await getRuns(100)).runs
  } catch (e) {
    ElMessage.error('历史加载失败：' + e.message)
  } finally {
    loading.value = false
  }
}

async function open(row) {
  drawer.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await getRun(row.run_id)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    detailLoading.value = false
  }
}

async function removeRun(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除该条测试历史（${row.run_id.slice(0, 8)}）？删除后不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteRun(row.run_id)
    ElMessage.success('已删除')
    await refresh()
  } catch (e) {
    ElMessage.error('删除失败：' + e.message)
  }
}

function fmtTime(ts) {
  if (!ts) return '—'
  return ts.replace('T', ' ').slice(0, 19)
}

function scoreOf(summary) {
  if (!summary) return null
  // 统一口径：一律显示「通过 xx%」（攻击轮 pass_rate = 防御得分，功能/恢复轮 = 通过判定占比）
  if (summary.pass_rate != null) return `通过 ${(summary.pass_rate * 100).toFixed(1)}%`
  // 旧数据兜底
  if (summary.defense_score != null) return `防御 ${(summary.defense_score * 100).toFixed(1)}%`
  if (summary.recovery_rate != null) return `恢复 ${(summary.recovery_rate * 100).toFixed(1)}%`
  return null
}
</script>

<template>
  <div class="hist-page">
    <header class="page-head">
      <div>
        <h2 class="page-title metal-text">测试历史</h2>
        <p class="page-sub">每次运行都是一条独立记录，点击行查看逐用例判定</p>
      </div>
      <el-button :loading="loading" @click="refresh">刷新</el-button>
    </header>

    <div class="glass-panel table-wrap">
      <el-table :data="runs" style="width: 100%" @row-click="open" v-loading="loading">
        <el-table-column label="run_id" width="130">
          <template #default="{ row }">
            <span class="run-id">{{ row.run_id.slice(0, 8) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="label" label="标签" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag
              size="small"
              effect="dark"
              :type="row.status === 'completed' ? 'success' : row.status === 'failed' ? 'danger' : 'primary'"
            >
              {{ row.status === 'completed' ? '已完成' : row.status === 'failed' ? '失败' : '运行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="结论概览" min-width="220">
          <template #default="{ row }">
            <span v-if="row.summary" class="counts">
              <el-tag
                v-for="(n, k) in row.summary.counts"
                :key="k"
                size="small"
                effect="plain"
                :type="verdictTag(k)"
                class="count-tag"
              >
                {{ k }} × {{ n }}
              </el-tag>
            </span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="统一得分" width="185">
          <template #default="{ row }">
            <template v-if="scoreOf(row.summary)">
              <span class="score">{{ scoreOf(row.summary) }}</span>
              <el-tag
                v-if="row.summary?.grade"
                size="small"
                effect="dark"
                :type="gradeTag(row.summary.grade)"
                class="grade-tag"
              >
                {{ row.summary.grade }}
              </el-tag>
            </template>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="170">
          <template #default="{ row }">
            <span class="dim">{{ fmtTime(row.started_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="86">
          <template #default="{ row }">
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="row.status === 'running'"
              @click.stop="removeRun(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="drawer" title="Run 详情" size="640px" class="run-drawer">
      <div v-if="detailLoading" class="dim center">加载中…</div>
      <template v-else-if="detail">
        <div v-if="detail.status === 'running'" class="glass-panel live-box">
          <div class="live-head">运行中 {{ detail.case_done }}/{{ detail.case_total || '?' }} 用例</div>
          <div class="run-cases">
            <el-tag v-for="c in detail.cases || []" :key="c.case_id" size="small" effect="dark" :type="verdictTag(c.verdict)">
              {{ c.case_id }} · {{ c.verdict }}
            </el-tag>
          </div>
        </div>
        <template v-else>
          <div class="detail-meta">
            <div class="meta-row"><span class="meta-k">run_id</span><span class="run-id">{{ detail.run_id }}</span></div>
            <div class="meta-row"><span class="meta-k">标签</span>{{ detail.label }}</div>
            <div class="meta-row" v-if="detail.summary">
              <span class="meta-k">判定分布</span>
              <el-tag
                v-for="(n, k) in detail.summary.counts"
                :key="k"
                size="small"
                effect="plain"
                :type="verdictTag(k)"
                class="count-tag"
              >
                {{ k }} × {{ n }}
              </el-tag>
            </div>
            <div class="meta-row" v-if="detail.summary">
              <span class="meta-k">统一得分</span>{{ scoreOf(detail.summary) || '—' }}
              <el-tag
                v-if="detail.summary.grade"
                size="small"
                effect="dark"
                :type="gradeTag(detail.summary.grade)"
              >
                {{ detail.summary.grade }}
              </el-tag>
            </div>
            <div class="meta-row interp" v-if="detail.summary?.interpretation">
              <span class="meta-k">结果解读</span>
              <span class="interp-body">{{ detail.summary.interpretation }}</span>
            </div>
          </div>
          <h4 class="sec-title">用例结果</h4>
          <div class="case-list">
            <div v-for="c in detail.cases" :key="c.case_id" class="case-item glass-panel">
              <div class="case-top">
                <span class="case-id">{{ c.case_id }}</span>
                <el-tag size="small" effect="dark" :type="verdictTag(c.verdict)">{{ c.verdict }}</el-tag>
                <span v-if="c.state" class="case-state">{{ c.state }}</span>
                <span class="case-tokens">tokens {{ c.tokens }} · 工具调用 {{ c.tool_calls }}</span>
              </div>
              <div v-if="c.final_answer" class="case-answer md-body" v-html="mdRender(c.final_answer)" />
              <div v-else class="case-empty">（无作答内容）</div>
            </div>
          </div>
        </template>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.hist-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
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

.table-wrap {
  flex: 1;
  padding: 8px;
  overflow: auto;
}

.run-id {
  color: var(--g-accent);
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12.5px;
}

.counts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.count-tag {
  margin-right: 4px;
}

.score {
  color: var(--g-accent);
  font-size: 13px;
}

.grade-tag {
  margin-left: 8px;
}

/* 结果解读卡片 */
.interp {
  align-items: flex-start;
  padding: 10px 12px;
  border-left: 2px solid var(--g-accent);
  border-radius: 6px;
  background: rgba(2, 6, 16, 0.35);
}

.interp-body {
  flex: 1;
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--g-text);
}

.dim {
  color: var(--g-text-dim);
  font-size: 12.5px;
}

.center {
  text-align: center;
  padding: 24px;
}

/* 抽屉 */
.detail-meta {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 18px;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 13px;
}

.meta-k {
  width: 60px;
  color: var(--g-text-dim);
  font-size: 12px;
}

.sec-title {
  font-size: 12px;
  letter-spacing: 0.15em;
  color: var(--g-text-dim);
  margin: 0 0 10px;
}

.case-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.case-item {
  padding: 12px 14px;
}

.case-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.case-id {
  font-size: 13px;
  font-weight: 600;
}

.case-tokens {
  margin-left: auto;
  font-size: 12px;
  color: var(--g-text-dim);
}

.case-answer {
  margin-top: 10px;
  max-height: 380px;
  overflow-y: auto;
  padding: 10px 14px;
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--g-text);
  background: rgba(2, 6, 16, 0.35);
  border: 1px solid var(--g-border);
  border-radius: 8px;
}

.case-state {
  font-size: 11.5px;
  color: var(--g-text-dim);
  border: 1px solid var(--g-border);
  border-radius: 999px;
  padding: 1px 8px;
}

.case-empty {
  margin-top: 8px;
  font-size: 12px;
  color: var(--g-text-dim);
}

.live-box {
  padding: 14px 16px;
}

.live-head {
  font-size: 13px;
  color: var(--g-accent);
  margin-bottom: 10px;
}

.run-cases {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
