<script setup>
/**
 * 测试中心 —— Task 卡片：悬停展示右侧测试详情（功能/关联API/用例/故障策略/已知结论），
 * 点击「运行测试」后台执行并轮询进度；每次运行都是独立的 run 记录。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { CATEGORY_META, getRun, getTasks, gradeTag, runTask, verdictTag } from '@/api/client'

const tasks = ref([])
const hoveredId = ref(null)
const running = reactive({})   // task_id -> {run_id, status, case_total, case_done, error, summary, cases}
const detailTask = computed(() => tasks.value.find((t) => t.id === hoveredId.value) || null)

let pollTimer = null

onMounted(async () => {
  try {
    tasks.value = (await getTasks()).tasks
  } catch (e) {
    ElMessage.error('任务注册表加载失败：' + e.message)
  }
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})

function hover(t) {
  hoveredId.value = t.id
}

async function start(t) {
  if (running[t.id]?.status === 'running') return
  try {
    const { run_id } = await runTask(t.id)
    running[t.id] = reactive({ run_id, status: 'running', case_total: 0, case_done: 0, cases: [], summary: null, error: null })
    poll(run_id, t.id)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function poll(runId, taskId) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const d = await getRun(runId)
      const r = running[taskId]
      if (!r) return
      r.status = d.status
      r.case_total = d.case_total ?? r.case_total
      r.case_done = d.case_done ?? r.case_done
      r.cases = d.cases || []
      r.summary = d.summary || null
      r.error = d.error || null
      if (d.status !== 'running') {
        clearInterval(pollTimer)
        refreshTasks() // run 落库后刷新卡片上的用例最新状态
      }
    } catch { /* 下一轮重试 */ }
  }, 2000)
}

function pct(r) {
  if (!r?.case_total) return 0
  return Math.min(100, Math.round(((r.case_done || 0) / r.case_total) * 100))
}

// 用例最新状态（灰 = 未测；其余颜色与判定 tag 一致：绿通过 / 黄注意 / 红失败）
const VERDICT_COLOR = { success: '#67c23a', warning: '#e6a23c', danger: '#f56c6c', info: '#94a3b8' }
const UNTESTED_COLOR = 'rgba(148, 163, 184, 0.3)'

function caseStatus(t, cid) {
  return t.case_status?.[cid] || ''
}

function statusColor(t, cid) {
  const v = caseStatus(t, cid)
  return v ? VERDICT_COLOR[verdictTag(v)] || VERDICT_COLOR.info : UNTESTED_COLOR
}

function statusTip(t, cid) {
  const v = caseStatus(t, cid)
  return v ? `${cid} · 最新状态 ${v}` : `${cid} · 未测`
}

function testedCount(t) {
  return (t.case_ids || []).filter((cid) => t.case_status?.[cid]).length
}

async function refreshTasks() {
  try {
    tasks.value = (await getTasks()).tasks
  } catch { /* 保留旧数据 */ }
}
</script>

<template>
  <div class="tc-page">
    <header class="page-head">
      <div>
        <h2 class="page-title metal-text">测试中心</h2>
        <p class="page-sub">悬停卡片查看测试详情，点击运行立即开测（每次运行独立记录）</p>
      </div>
    </header>

    <div class="tc-layout">
      <!-- 左：任务卡片网格 -->
      <div class="card-grid">
        <div
          v-for="t in tasks"
          :key="t.id"
          class="task-card glass-panel"
          :class="{ active: hoveredId === t.id }"
          @mouseenter="hover(t)"
          @focusin="hover(t)"
          tabindex="0"
        >
          <div class="card-top">
            <el-tag size="small" :type="CATEGORY_META[t.category]?.tag" effect="dark">
              {{ CATEGORY_META[t.category]?.label || t.category }}
            </el-tag>
            <span class="card-cases">{{ t.case_ids.length }} 用例</span>
          </div>
          <h3 class="card-name">{{ t.name }}</h3>
          <p class="card-desc">{{ t.description }}</p>
          <!-- 用例最新状态：灰 = 未测，绿/黄/红 = 最近一次判定 -->
          <div v-if="t.case_ids.length" class="case-status-row">
            <el-tooltip v-for="cid in t.case_ids" :key="cid" :content="statusTip(t, cid)" placement="top">
              <span class="st-dot" :style="{ background: statusColor(t, cid) }" />
            </el-tooltip>
            <span class="st-count">已测 {{ testedCount(t) }}/{{ t.case_ids.length }}</span>
          </div>
          <div class="card-foot">
            <button
              class="run-btn"
              :disabled="running[t.id]?.status === 'running'"
              @click.stop="start(t)"
            >
              {{ running[t.id]?.status === 'running' ? '执行中…' : '运行测试' }}
            </button>
          </div>

          <!-- 运行进度（内嵌卡片底部） -->
          <div v-if="running[t.id]" class="card-run">
            <el-progress
              :percentage="pct(running[t.id])"
              :stroke-width="6"
              :show-text="false"
              :color="running[t.id].status === 'failed' ? '#f56c6c' : '#38f2d8'"
            />
            <div class="run-meta">
              <span>{{ running[t.id].case_done }}/{{ running[t.id].case_total || '?' }} 用例</span>
              <span class="run-id">run {{ running[t.id].run_id.slice(0, 8) }}</span>
            </div>
            <div class="run-cases">
              <el-tag
                v-for="c in running[t.id].cases"
                :key="c.case_id"
                size="small"
                :type="verdictTag(c.verdict)"
                effect="dark"
              >
                {{ c.case_id.replace(/^atk-|^w1-/, '') }}·{{ c.verdict }}
              </el-tag>
            </div>
            <div v-if="running[t.id].status === 'completed' && running[t.id].summary" class="run-done">
              <template v-if="running[t.id].summary.pass_rate != null">
                统一得分 通过 {{ (running[t.id].summary.pass_rate * 100).toFixed(1) }}%
                <el-tag
                  v-if="running[t.id].summary.grade"
                  size="small"
                  effect="dark"
                  :type="gradeTag(running[t.id].summary.grade)"
                  class="done-grade"
                >
                  {{ running[t.id].summary.grade }}
                </el-tag>
              </template>
              · 完整结果见「测试历史」
            </div>
            <div v-if="running[t.id].status === 'failed'" class="run-fail">
              {{ running[t.id].error || '执行失败' }}
            </div>
          </div>
        </div>
      </div>

      <!-- 右：悬停详情面板 -->
      <aside class="detail-panel glass-panel">
        <template v-if="detailTask">
          <div class="detail-head">
            <el-tag size="small" :type="CATEGORY_META[detailTask.category]?.tag" effect="dark">
              {{ CATEGORY_META[detailTask.category]?.label || detailTask.category }}
            </el-tag>
            <h3 class="detail-name">{{ detailTask.name }}</h3>
          </div>
          <p class="detail-desc">{{ detailTask.description }}</p>

          <h4 class="detail-sec">关联焰哨 API</h4>
          <div class="api-list">
            <code v-for="a in detailTask.apis" :key="a" class="api-item">{{ a }}</code>
          </div>

          <h4 class="detail-sec">评测用例（最新状态）</h4>
          <div class="case-chips">
            <el-tag
              v-for="c in detailTask.case_ids"
              :key="c"
              size="small"
              :type="detailTask.case_status?.[c] ? verdictTag(detailTask.case_status[c]) : 'info'"
              :effect="detailTask.case_status?.[c] ? 'dark' : 'plain'"
            >
              {{ c }} · {{ detailTask.case_status?.[c] || '未测' }}
            </el-tag>
            <span v-if="!detailTask.case_ids.length" class="dim">套件全量用例</span>
          </div>

          <template v-if="detailTask.faults.length">
            <h4 class="detail-sec">故障策略</h4>
            <div class="case-chips">
              <el-tag v-for="f in detailTask.faults" :key="f" size="small" type="warning" effect="plain">
                {{ f }}
              </el-tag>
            </div>
          </template>

          <div v-if="detailTask.prerequisite" class="note prereq-note">
            <div class="note-k">运行前置条件</div>{{ detailTask.prerequisite }}
          </div>
          <div v-if="detailTask.honeypot" class="note warn-note">运行前自动种入知识库蜜罐，跑完自动清除</div>
          <div v-if="detailTask.risk_note" class="note risk-note">{{ detailTask.risk_note }}</div>
        </template>

        <div v-else class="detail-empty">
          <div class="detail-empty-icon">◈</div>
          <p>将鼠标悬停到左侧任务卡片，这里会展示该任务测试哪些功能、覆盖哪些 API 与用例。</p>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.tc-page {
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

.tc-layout {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 18px;
  min-height: 0;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
  align-content: start;
  overflow-y: auto;
  padding: 4px;
}

.task-card {
  padding: 16px 18px;
  cursor: pointer;
  transition: all 0.25s ease;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-card:hover,
.task-card.active {
  border-color: var(--g-border-glow);
  box-shadow: 0 0 20px rgba(56, 242, 216, 0.14), 0 8px 32px rgba(2, 6, 16, 0.45);
  transform: translateY(-2px);
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-cases {
  font-size: 12px;
  color: var(--g-text-dim);
}

.card-name {
  margin: 0;
  font-size: 15.5px;
}

.card-desc {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--g-text-dim);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.case-status-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.st-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  cursor: default;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.st-dot:hover {
  transform: scale(1.35);
  box-shadow: 0 0 8px rgba(56, 242, 216, 0.45);
}

.st-count {
  margin-left: auto;
  font-size: 11px;
  color: var(--g-text-dim);
}

.card-foot {
  margin-top: auto;
}

.run-btn {
  width: 100%;
  padding: 8px 0;
  border-radius: 9px;
  border: 1px solid var(--g-border-glow);
  background: linear-gradient(135deg, rgba(56, 242, 216, 0.14), rgba(59, 130, 246, 0.14));
  color: var(--g-accent);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.25s ease;
}

.run-btn:hover:not(:disabled) {
  box-shadow: 0 0 14px rgba(56, 242, 216, 0.3);
}

.run-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.card-run {
  border-top: 1px solid var(--g-border);
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.run-meta {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--g-text-dim);
}

.run-id {
  color: var(--g-accent);
}

.run-cases {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.run-done {
  font-size: 12.5px;
  color: var(--g-ok);
}

.done-grade {
  margin-left: 6px;
}

.run-fail {
  font-size: 12.5px;
  color: var(--g-danger);
}

/* ---------- 详情面板 ---------- */
.detail-panel {
  padding: 20px 22px;
  overflow-y: auto;
  align-self: start;
  position: sticky;
  top: 0;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.detail-name {
  margin: 0;
  font-size: 16px;
}

.detail-desc {
  font-size: 13px;
  line-height: 1.8;
  color: var(--g-text);
  margin: 0 0 6px;
}

.detail-sec {
  font-size: 12px;
  letter-spacing: 0.15em;
  color: var(--g-text-dim);
  margin: 16px 0 8px;
}

.api-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.api-item {
  font-size: 11.5px;
  padding: 5px 9px;
  border-radius: 6px;
  background: rgba(56, 242, 216, 0.06);
  border: 1px solid var(--g-border);
  color: #9fd8ff;
  overflow-wrap: anywhere;
}

.case-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.dim {
  font-size: 12px;
  color: var(--g-text-dim);
}

.note {
  margin-top: 14px;
  font-size: 12.5px;
  line-height: 1.7;
  padding: 10px 12px;
  border-radius: 9px;
}

.warn-note {
  background: rgba(230, 162, 60, 0.1);
  border: 1px solid rgba(230, 162, 60, 0.35);
  color: var(--g-warn);
}

.prereq-note {
  background: rgba(230, 162, 60, 0.1);
  border: 1px solid rgba(230, 162, 60, 0.35);
  color: #f3c98b;
}

.note-k {
  font-weight: 600;
  color: var(--g-warn);
  margin-bottom: 2px;
}

.risk-note {
  background: rgba(245, 108, 108, 0.08);
  border: 1px solid rgba(245, 108, 108, 0.3);
  color: #f0a3a3;
}

.detail-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  text-align: center;
  color: var(--g-text-dim);
  font-size: 13px;
  line-height: 1.8;
  padding: 0 12px;
}

.detail-empty-icon {
  font-size: 34px;
  color: var(--g-accent);
  opacity: 0.6;
}
</style>
