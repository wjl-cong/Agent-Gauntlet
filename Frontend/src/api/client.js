/**
 * AgentGauntlet 平台 API 封装（FastAPI /api/v1，dev 经 vite 代理到 127.0.0.1:8100）。
 */
const BASE = '/api/v1'

async function request(path, options = {}) {
    const res = await fetch(`${BASE}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    })
    if (!res.ok) {
        let detail = res.statusText
        try {
            const j = await res.json()
            detail = j.detail || detail
        } catch { /* 保留 statusText */ }
        throw new Error(`API ${res.status}: ${detail}`)
    }
    return res.json()
}

/** 健康检查 */
export function getHealth() {
    return request('/health')
}

/** 任务注册表（测试中心卡片 + 悬停详情） */
export function getTasks() {
    return request('/tasks')
}

/** 运行单个测试任务（后台异步，返回 {run_id, status}） */
export function runTask(taskId) {
    return request(`/tasks/${taskId}/run`, { method: 'POST' })
}

/** 评测历史列表 */
export function getRuns(limit = 50) {
    return request(`/runs?limit=${limit}`)
}

/** run 详情（运行中=进度；已完成=落库结果） */
export function getRun(runId) {
    return request(`/runs/${runId}`)
}

/** 删除一条测试历史（运行中的 run 会被拒绝） */
export function deleteRun(runId) {
    return request(`/runs/${runId}`, { method: 'DELETE' })
}

/** 焰哨 openapi + 测试覆盖映射 */
export function getApis() {
    return request('/apis')
}

/**
 * Agent 四阶段对话（SSE 帧流）。
 * POST + ReadableStream 逐帧解析 `data: {...}`，每帧回调 onFrame(frame)。
 * 结束帧 {type:'done'} / 中途 {type:'error'}。
 */
export async function streamAgentChat(question, onFrame) {
    const res = await fetch(`${BASE}/agent/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
    })
    if (!res.ok) {
        let detail = res.statusText
        try {
            const j = await res.json()
            detail = j.detail || detail
        } catch { /* 保留 statusText */ }
        throw new Error(`API ${res.status}: ${detail}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buf = ''
    for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop()
        for (const part of parts) {
            const line = part.split('\n').find((l) => l.startsWith('data:'))
            if (!line) continue
            try {
                onFrame(JSON.parse(line.slice(5).trim()))
            } catch { /* 跳过坏帧 */ }
        }
    }
}

/** 判定结果 → Element Plus tag 类型 */
export function verdictTag(v) {
    if (['LEVEL_1', 'LEVEL_2', 'BLOCKED', 'NOT_INJECTED'].includes(v)) return 'success'
    if (['SUSPECT_FABRICATION', 'NOT_TRIGGERED'].includes(v)) return 'warning'
    if (['COMPROMISED', 'LEAKED_PROMPT', 'FAILURE'].includes(v)) return 'danger'
    return 'info'
}

/** 统一评分等级 → tag 类型 */
export function gradeTag(g) {
    if (g === '优秀' || g === '良好') return 'success'
    if (g === '一般') return 'warning'
    if (g === '待改进') return 'danger'
    return 'info'
}

/** 任务类别 → 展示元数据 */
export const CATEGORY_META = {
    functional: { label: '功能', tag: 'success' },
    chaos: { label: '故障注入', tag: 'warning' },
    attack: { label: '攻击', tag: 'danger' },
}