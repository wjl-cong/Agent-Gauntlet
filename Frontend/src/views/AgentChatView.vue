<script setup>
/**
 * Agent 对话首页 —— 用户提问，评测 Agent 四阶段自治完成：
 * 01 意图分析（LLM 流式）→ 02 测试规划（任务选定）→ 03 自主执行（逐用例推帧）→ 04 评测结论（LLM 流式）
 */
import { computed, nextTick, reactive, ref } from 'vue'
import { mdRender } from '@/utils/md'
import { CATEGORY_META, streamAgentChat } from '@/api/client'

const input = ref('')
const sending = ref(false)
const threadRef = ref(null)

const EXAMPLES = [
  '全面体检一下焰哨的安全防御能力',
  '测一下角色扮演攻击',
  '跑一遍功能回归测试',
  '故障恢复能力怎么样',
]

const messages = reactive([])

/* ---------- 对话历史（localStorage 持久化，每个对话一条独立记录，不互相覆盖） ---------- */
const CHAT_KEY = 'gauntlet_chats'
let currentChatId = null

const sessions = ref(loadSessions())
const histDrawer = ref(false)

function loadSessions() {
  try {
    return JSON.parse(localStorage.getItem(CHAT_KEY) || '[]')
  } catch {
    return []
  }
}

function saveSessions() {
  try {
    localStorage.setItem(CHAT_KEY, JSON.stringify(sessions.value.slice(0, 50)))
  } catch { /* 存储满时忽略 */ }
}

/** 会话结束时持久化：新对话新建记录，继续历史对话则原地更新该记录 */
function persistChat() {
  if (!messages.length) return
  const now = new Date().toLocaleString('zh-CN', { hour12: false })
  let s = sessions.value.find((x) => x.id === currentChatId)
  if (!s) {
    currentChatId = 'c' + Date.now()
    s = {
      id: currentChatId,
      title: (messages.find((m) => m.role === 'user')?.text || '新对话').slice(0, 30),
      time: now,
      messages: [],
    }
    sessions.value.unshift(s)
  }
  s.time = now
  s.messages = JSON.parse(JSON.stringify(messages))
  saveSessions()
}

function newChat() {
  if (sending.value) return
  messages.length = 0
  currentChatId = null
}

function restoreChat(s) {
  if (sending.value) return
  currentChatId = s.id
  messages.length = 0
  for (const m of s.messages || []) messages.push(JSON.parse(JSON.stringify(m)))
  histDrawer.value = false
  _touch()
}

function delSession(s) {
  sessions.value = sessions.value.filter((x) => x.id !== s.id)
  saveSessions()
  if (currentChatId === s.id) currentChatId = null
}

const canSend = computed(() => !!input.value.trim() && !sending.value)

function _touch(uuidRef) {
  const el = threadRef.value
  if (el) nextTick(() => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }))
}

async function send(preset) {
  const q = (preset ?? input.value ?? '').trim()
  if (!q || sending.value) return
  input.value = ''
  sending.value = true
  messages.push({ role: 'user', text: q })

  const m = reactive({
    role: 'assistant',
    analyzing: true,
    analysis: '',
    plan: null,
    exec: {},
    execOrder: [],
    summarizing: false,
    summary: '',
    error: null,
    done: false,
  })
  messages.push(m)
  _touch()

  const onFrame = (f) => {
    const { phase, type } = f
    if (phase === 'analyze' && type === 'text') {
      m.analysis += f.delta
    } else if (phase === 'analyze' && type === 'status') {
      m.analyzing = true
    } else if (phase === 'plan' && type === 'tasks') {
      m.analyzing = false
      m.plan = { task_ids: f.task_ids, tasks: f.tasks }
    } else if (phase === 'execute') {
      if (type === 'task_start') {
        m.exec[f.task_id] = reactive({
          name: f.name, category: f.category, case_total: f.case_total,
          cases: [], notes: [], done: false, run_id: null, summary: null, error: null,
        })
        m.execOrder.push(f.task_id)
      } else if (type === 'case') {
        const t = m.exec[f.task_id]
        if (t) t.cases.push(f.data)
      } else if (type === 'note') {
        const t = m.execOrder.length ? m.exec[m.execOrder[m.execOrder.length - 1]] : null
        if (t) t.notes.push(f.message)
      } else if (type === 'task_done') {
        const t = m.exec[f.task_id]
        if (t) {
          t.done = true
          t.run_id = f.run_id || null
          t.summary = f.summary || null
          t.error = f.error || null
        }
      }
    } else if (phase === 'summarize' && type === 'text') {
      m.summarizing = false
      m.summary += f.delta
    } else if (phase === 'summarize' && type === 'status') {
      m.summarizing = true
    } else if (type === 'error') {
      m.error = f.message
    } else if (type === 'done') {
      m.done = true
      m.analyzing = false
      m.summarizing = false
    }
    _touch()
  }

  try {
    await streamAgentChat(q, onFrame)
  } catch (e) {
    m.error = e.message
    m.done = true
  } finally {
    sending.value = false
    persistChat()
    _touch()
  }
}

function onKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

const STAGES = [
  { no: '01', label: '意图分析' },
  { no: '02', label: '测试规划' },
  { no: '03', label: '自主执行' },
  { no: '04', label: '评测结论' },
]
</script>

<template>
  <div class="chat-page">
    <div class="chat-toolbar">
      <span class="toolbar-info">{{ sessions.length ? `${sessions.length} 条历史对话` : '暂无历史对话' }}</span>
      <div class="toolbar-btns">
        <button class="tool-btn" :disabled="sending" @click="newChat">＋ 新对话</button>
        <button class="tool-btn" @click="histDrawer = true">历史对话</button>
      </div>
    </div>

    <div class="thread" ref="threadRef">
      <!-- 空态 hero -->
      <div v-if="!messages.length" class="hero glass-panel">
        <div class="hero-kicker">AGENT · AUTONOMOUS RED TEAM</div>
        <h1 class="hero-title metal-text">问一句话，Agent 自己规划并开测</h1>
        <p class="hero-sub">
          描述你想考察焰哨的能力或风险，评测 Agent 将自动完成
          意图分析 → 测试规划 → 自主执行 → 评测结论 四个阶段，全程流式直播。
        </p>
        <div class="examples">
          <button v-for="e in EXAMPLES" :key="e" class="example-chip" @click="send(e)">
            {{ e }}
          </button>
        </div>
      </div>

      <!-- 消息 -->
      <template v-for="(m, i) in messages" :key="i">
        <div v-if="m.role === 'user'" class="msg-user">
          <div class="user-bubble">{{ m.text }}</div>
        </div>

        <div v-else class="msg-assistant glass-panel">
          <div class="stage-rail">
            <div v-for="s in STAGES" :key="s.no" class="rail-node"
              :class="{ active: s.no === '01' }">
              <span class="rail-no">{{ s.no }}</span>
            </div>
          </div>

          <div class="stage-body">
            <!-- 01 意图分析 -->
            <section v-if="m.analyzing || m.analysis" class="stage">
              <header class="stage-head">
                <span class="stage-no">01</span><span class="stage-label">意图分析</span>
                <span v-if="m.analyzing && !m.plan" class="pulse-dots"><i /><i /><i /></span>
              </header>
              <div class="stream-text">{{ m.analysis }}<span v-if="m.analyzing" class="caret" /></div>
            </section>

            <!-- 02 测试规划 -->
            <section v-if="m.plan" class="stage">
              <header class="stage-head">
                <span class="stage-no">02</span><span class="stage-label">测试规划</span>
                <el-tag v-if="m.plan.task_ids.length" size="small" type="info" effect="plain">
                  {{ m.plan.task_ids.length }} 个任务
                </el-tag>
              </header>
              <div v-if="m.plan.tasks.length" class="plan-tasks">
                <div v-for="t in m.plan.tasks" :key="t.id" class="plan-task">
                  <el-tag size="small" :type="CATEGORY_META[t.category]?.tag || 'info'" effect="dark">
                    {{ CATEGORY_META[t.category]?.label || t.category }}
                  </el-tag>
                  <span class="plan-name">{{ t.name }}</span>
                  <span class="plan-meta">{{ t.case_ids.length || '套件' }} 用例</span>
                </div>
              </div>
              <div v-else class="plan-empty">未匹配到可执行的测试任务</div>
            </section>

            <!-- 03 自主执行 -->
            <section v-if="m.execOrder.length" class="stage">
              <header class="stage-head">
                <span class="stage-no">03</span><span class="stage-label">自主执行</span>
                <span v-if="!m.done" class="pulse-dots"><i /><i /><i /></span>
              </header>
              <div v-for="tid in m.execOrder" :key="tid" class="exec-task">
                <div class="exec-head">
                  <span class="exec-name">{{ m.exec[tid].name }}</span>
                  <el-tag v-if="!m.exec[tid].done" size="small" type="primary" effect="plain">执行中</el-tag>
                  <template v-else>
                    <el-tag v-if="m.exec[tid].error" size="small" type="danger" effect="dark">失败</el-tag>
                    <el-tag v-else size="small" type="success" effect="plain">完成</el-tag>
                  </template>
                </div>
                <div v-if="m.exec[tid].notes.length" class="exec-notes">
                  <div v-for="(n, ni) in m.exec[tid].notes" :key="ni" class="exec-note">{{ n }}</div>
                </div>
                <div class="exec-cases">
                  <div v-for="c in m.exec[tid].cases" :key="c.case_id" class="case-row">
                    <span class="case-id">{{ c.case_id }}</span>
                    <el-tag size="small" effect="dark" class="case-verdict">{{ c.verdict }}</el-tag>
                    <span class="case-tokens">tokens {{ c.tokens }}</span>
                  </div>
                </div>
                <div v-if="m.exec[tid].summary" class="exec-summary">
                  <template v-if="m.exec[tid].summary.defense_score != null">
                    防御得分 {{ (m.exec[tid].summary.defense_score * 100).toFixed(1) }}%
                  </template>
                  <template v-else-if="m.exec[tid].summary.recovery_rate != null">
                    恢复率 {{ (m.exec[tid].summary.recovery_rate * 100).toFixed(1) }}%
                  </template>
                  <span class="run-id">run {{ (m.exec[tid].run_id || '').slice(0, 8) }}</span>
                </div>
              </div>
            </section>

            <!-- 04 评测结论（流式阶段纯文本，完成后 markdown 渲染） -->
            <section v-if="m.summarizing || m.summary" class="stage">
              <header class="stage-head">
                <span class="stage-no">04</span><span class="stage-label">评测结论</span>
                <span v-if="m.summarizing && !m.done" class="pulse-dots"><i /><i /><i /></span>
              </header>
              <div v-if="!m.done" class="stream-text summary">{{ m.summary }}<span v-if="m.summarizing" class="caret" /></div>
              <div v-else class="stream-text summary md-body" v-html="mdRender(m.summary)" />
            </section>

            <el-alert v-if="m.error" :title="'执行中断：' + m.error" type="error" :closable="false" class="chat-error" />
          </div>
        </div>
      </template>
    </div>

    <!-- 输入区 -->
    <div class="composer glass-panel">
      <textarea
        v-model="input"
        class="composer-input"
        rows="2"
        placeholder="向评测 Agent 下达测试指令…（Enter 发送，Shift+Enter 换行）"
        :disabled="sending"
        @keydown="onKeydown"
      />
      <button class="send-btn" :disabled="!canSend" @click="send()">
        <span v-if="!sending">发送</span>
        <span v-else class="pulse-dots"><i /><i /><i /></span>
      </button>
    </div>

    <!-- 对话历史抽屉 -->
    <el-drawer v-model="histDrawer" title="对话历史" size="360px" class="hist-drawer">
      <div v-if="!sessions.length" class="hist-empty">暂无历史对话</div>
      <div v-else class="sess-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="sess-item"
          :class="{ current: s.id === currentChatId }"
        >
          <div class="sess-main" @click="restoreChat(s)">
            <div class="sess-title">{{ s.title }}</div>
            <div class="sess-time">{{ s.time }} · {{ (s.messages || []).length }} 条消息</div>
          </div>
          <button class="sess-del" @click.stop="delSession(s)">删除</button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 980px;
  margin: 0 auto;
  gap: 14px;
}

.thread {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 8px 4px;
}

/* ---------- 空态 ---------- */
.hero {
  margin: auto;
  padding: 46px 56px;
  text-align: center;
}

.hero-kicker {
  font-size: 11px;
  letter-spacing: 0.35em;
  color: var(--g-text-dim);
  margin-bottom: 14px;
}

.hero-title {
  font-size: 30px;
  margin: 0 0 12px;
}

.hero-sub {
  color: var(--g-text-dim);
  font-size: 14px;
  line-height: 1.8;
  max-width: 560px;
  margin: 0 auto 24px;
}

.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: center;
}

.example-chip {
  padding: 8px 16px;
  border-radius: 999px;
  border: 1px solid var(--g-border);
  background: var(--g-panel);
  color: var(--g-text-dim);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.25s ease;
}

.example-chip:hover {
  color: var(--g-accent);
  border-color: var(--g-border-glow);
  box-shadow: 0 0 14px rgba(56, 242, 216, 0.18);
}

/* ---------- 消息 ---------- */
.msg-user {
  display: flex;
  justify-content: flex-end;
}

.user-bubble {
  max-width: 72%;
  padding: 12px 18px;
  border-radius: 14px 14px 4px 14px;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.22), rgba(56, 242, 216, 0.14));
  border: 1px solid var(--g-border-glow);
  font-size: 14px;
  line-height: 1.7;
}

.msg-assistant {
  display: flex;
  gap: 16px;
  padding: 18px 22px;
}

/* 左侧阶段轨道 */
.stage-rail {
  display: flex;
  flex-direction: column;
  gap: 26px;
  padding-top: 4px;
}

.rail-node {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid var(--g-border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: var(--g-text-dim);
  position: relative;
}

.rail-node.active {
  border-color: var(--g-border-glow);
  color: var(--g-accent);
  box-shadow: 0 0 12px rgba(56, 242, 216, 0.25);
}

.rail-node:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 32px;
  left: 50%;
  width: 1px;
  height: 24px;
  background: linear-gradient(180deg, var(--g-border-glow), transparent);
}

.stage-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.stage {
  border-left: 2px solid rgba(56, 242, 216, 0.35);
  padding-left: 16px;
}

.stage-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.stage-no {
  font-size: 11px;
  letter-spacing: 0.2em;
  color: var(--g-accent);
}

.stage-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--g-text);
}

.stream-text {
  font-size: 13.5px;
  line-height: 1.85;
  color: var(--g-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.stream-text.summary {
  color: var(--g-text);
}

/* 完成后的 md 渲染接管排版（覆盖 pre-wrap） */
.stream-text.md-body {
  white-space: normal;
}

.caret {
  display: inline-block;
  width: 7px;
  height: 15px;
  margin-left: 2px;
  vertical-align: -2px;
  background: var(--g-accent);
  animation: blink 1s steps(1) infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}

/* 规划任务 */
.plan-tasks {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plan-task {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--g-panel-strong);
  border: 1px solid var(--g-border);
}

.plan-name {
  font-size: 13.5px;
}

.plan-meta {
  margin-left: auto;
  font-size: 12px;
  color: var(--g-text-dim);
}

.plan-empty {
  font-size: 13px;
  color: var(--g-text-dim);
}

/* 执行任务 */
.exec-task {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--g-panel-strong);
  border: 1px solid var(--g-border);
  margin-bottom: 10px;
}

.exec-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.exec-name {
  font-size: 13.5px;
  font-weight: 600;
}

.exec-notes {
  margin-bottom: 6px;
}

.exec-note {
  font-size: 12px;
  color: var(--g-warn);
}

.exec-cases {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.case-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
}

.case-id {
  color: var(--g-text-dim);
  min-width: 150px;
}

.case-tokens {
  margin-left: auto;
  color: var(--g-text-dim);
}

.exec-summary {
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--g-accent);
  display: flex;
  gap: 12px;
}

.run-id {
  color: var(--g-text-dim);
}

.chat-error {
  margin-top: 4px;
}

/* ---------- 流式脉冲点 ---------- */
.pulse-dots {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}

.pulse-dots i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--g-accent);
  animation: pulse 1.2s ease infinite;
}

.pulse-dots i:nth-child(2) { animation-delay: 0.2s; }
.pulse-dots i:nth-child(3) { animation-delay: 0.4s; }

@keyframes pulse {
  0%, 100% { opacity: 0.25; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.1); }
}

/* ---------- 输入区 ---------- */
.composer {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  padding: 12px 14px;
}

.composer-input {
  flex: 1;
  resize: none;
  border: none;
  outline: none;
  background: transparent;
  color: var(--g-text);
  font-size: 14px;
  line-height: 1.6;
  font-family: inherit;
}

.composer-input::placeholder {
  color: var(--g-text-dim);
}

.send-btn {
  min-width: 84px;
  padding: 10px 0;
  border-radius: 10px;
  border: 1px solid var(--g-border-glow);
  background: linear-gradient(135deg, rgba(56, 242, 216, 0.18), rgba(59, 130, 246, 0.18));
  color: var(--g-accent);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.25s ease;
}

.send-btn:hover:not(:disabled) {
  box-shadow: 0 0 16px rgba(56, 242, 216, 0.3);
}

.send-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* ---------- 工具栏 / 对话历史 ---------- */
.chat-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.toolbar-info {
  font-size: 12px;
  color: var(--g-text-dim);
}

.toolbar-btns {
  display: flex;
  gap: 8px;
}

.tool-btn {
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid var(--g-border);
  background: var(--g-panel);
  color: var(--g-text-dim);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.25s ease;
}

.tool-btn:hover:not(:disabled) {
  color: var(--g-accent);
  border-color: var(--g-border-glow);
  box-shadow: 0 0 12px rgba(56, 242, 216, 0.18);
}

.tool-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.hist-empty {
  text-align: center;
  color: var(--g-text-dim);
  font-size: 13px;
  padding: 32px 0;
}

.sess-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sess-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--g-border);
  background: var(--g-panel-strong);
  cursor: pointer;
  transition: all 0.2s ease;
}

.sess-item:hover,
.sess-item.current {
  border-color: var(--g-border-glow);
}

.sess-main {
  flex: 1;
  min-width: 0;
}

.sess-title {
  font-size: 13px;
  color: var(--g-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sess-time {
  margin-top: 3px;
  font-size: 11.5px;
  color: var(--g-text-dim);
}

.sess-del {
  border: none;
  background: none;
  color: #f0a3a3;
  font-size: 12px;
  cursor: pointer;
  opacity: 0.75;
}

.sess-del:hover {
  opacity: 1;
}
</style>
