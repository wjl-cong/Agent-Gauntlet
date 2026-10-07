# AgentGauntlet

#### 介绍

AgentGauntlet 是一个面向大语言模型智能体的红队评测平台，以「故障注入 + 对抗攻击 + 判定评分」为核心，对业务智能体实施功能、故障、攻击三个维度的自动化评测。默认被测对象为焰哨（Yanshao）森林火险业务智能体。

核心特性：

- **轨迹驱动判定**：五级恢复判定（含恢复率公式）与四级越界判定（含防御得分公式），全部基于执行轨迹的确定性规则，不引入生成式模型参与判定，可单测、可复现
- **受控故障注入**：声明式策略文件配置服务异常 / 超时两类故障，支持按概率与按调用次序两种触发模式，注入异常与真实故障同构，被测方无法区分评测流量
- **对抗攻击载荷库**：角色扮演 / 指令覆盖 / 目标劫持三类直接注入，知识库蜜罐 / 工具返回夹带两类间接注入，全部载荷携带全局唯一哨兵串支持泄露检测与证据归因
- **输入回声假阳性剔除**：哨兵串计数比较 + 空白归一化，消除模板化兜底回答原样回显查询造成的误判
- **单一执行核心**：命令行、REST 服务、四阶段流式评测智能体三条链路复用同一执行引擎，判定口径一致
- **四页可视化控制台**：Agent 评测会话（四阶段流式直播）/ 测试中心（11 项任务卡片）/ 测试历史（判定分布与逐用例详情）/ 接口测试规划（覆盖三分类分析）

真机评测结论（2026-10-03，初测 → 加固 → 复测两轮对照）：故障注入轮 6 例实际注入全部诚实降级，恢复率 100%；攻击初测暴露 7 例失守，其中系统提示词整段泄露（LEAKED_PROMPT）为最高危发现，防御得分 41.7%；焰哨上线四条提示词防注入条款、平台修复 8 项判定与执行缺陷后复测，系统提示词泄露清零（1 → 0），知识库蜜罐通道从 0 条可测提升至 3/3 防御，20 条攻击用例全部完成有效判定，防御得分提升至 52.6%；输出侧确定性护栏已开发完成，预期将剩余失守全部转为防御。

#### 软件架构

```
┌─────────────────────────────────────────────────────────┐
│  Frontend（Vue3 + Element Plus，端口 5174）               │
│  Agent 评测会话 / 测试中心 / 测试历史 / 接口测试规划          │
└──────────────────────┬──────────────────────────────────┘
                       │ REST / SSE（/api/v1/*）
┌──────────────────────▼──────────────────────────────────┐
│  Backend 展示服务（FastAPI，端口 8100）                    │
├─────────────────────────────────────────────────────────┤
│  GauntletAgent（四阶段流式编排：analyze→plan→execute→summarize） │
├─────────────────────────────────────────────────────────┤
│  评测执行引擎（runner + judge + attacks + chaos）          │
├─────────────────────────────────────────────────────────┤
│  被测对象适配层（targets：登录 / 任务创建 / SSE 采集 / 审批恢复） │
└───────────┬─────────────────────────────┬───────────────┘
            │ HTTP / SSE                  │ SQL
┌───────────▼───────────┐    ┌────────────▼───────────────┐
│  被测智能体（:8000）     │    │  PostgreSQL（gauntlet schema）│
└───────────────────────┘    └────────────────────────────┘
```

技术栈：

- 后端：Python 3.11 / FastAPI / Pydantic / Typer / asyncpg / httpx
- 前端：Vue 3 / Vue Router / Element Plus / Vite / marked + DOMPurify
- 数据：PostgreSQL（评测数据存储于独立 `gauntlet` schema，与业务数据隔离）
- 大模型：通义千问系列（OpenAI 兼容接口；Agent 对话与评测结论流式生成）

目录结构：

```
agent-gauntlet/
├── Backend/
│   ├── src/gauntlet/
│   │   ├── runner/        # 评测执行引擎（并发执行 / 预算熔断 / 异常隔离）
│   │   ├── judge/         # 恢复判定器（五级判定）
│   │   ├── attacks/       # 攻击载荷库 / 越界判定器 / 蜜罐管理
│   │   ├── chaos/         # 故障注入引擎与策略装载校验
│   │   ├── targets/       # 被测对象适配层（登录 / 事件流采集 / 审批恢复）
│   │   ├── agent/         # 四阶段流式评测智能体
│   │   ├── api/           # FastAPI 展示服务（REST + SSE）
│   │   ├── registry.py    # 评测任务注册中心（11 项任务）
│   │   └── config.py / models.py / db.py / cli.py
│   ├── suites/            # 评测用例套件（8 条功能用例 + 20 条攻击用例）
│   ├── faults/            # 故障策略文件（基线故障 / 工具夹带）
│   └── tests/             # pytest 测试套件
├── Frontend/
│   └── src/views/         # 评测会话 / 测试中心 / 测试历史 / 接口规划四页
└── docs/                  # 设计文档、进度记录与论文图源
```

#### 安装教程

1. 环境要求：Python 3.11、Node.js 18+、PostgreSQL 14+；被测智能体另行部署
2. 后端安装与配置

```bash
cd Backend
pip install -e .
copy .env.example .env    # Windows；Linux 使用 cp .env.example .env
```

编辑 `Backend/.env` 配置关键环境变量：

```ini
GAUNTLET_DSN=postgresql://postgres:postgres@localhost:5432/fire_agent
GAUNTLET_YANSHAO_BASE_URL=http://127.0.0.1:8000
GAUNTLET_YANSHAO_USER=评测账号
GAUNTLET_YANSHAO_PASSWORD=评测密码
GAUNTLET_TOKEN_BUDGET=2000000
GAUNTLET_JUDGE_MODEL=qwen-max
GAUNTLET_LLM_API_KEY=大模型服务密钥
GAUNTLET_LLM_MODEL=qwen3.7-flash
```

评测数据模式（gauntlet schema）在首次运行时自动创建。

3. 前端安装

```bash
cd Frontend
npm install
```

4. 启动服务

```bash
# 后端（端口 8100）
uvicorn gauntlet.api.main:app --host 0.0.0.0 --port 8100

# 前端开发服务（端口 5174，/api/v1 前缀代理至后端）
cd Frontend
npm run dev
```

#### 使用说明

1. 命令行评测

```bash
# W1 功能 + 故障注入轮
gauntlet run --faults faults/w1-baseline.yaml --label "w1-chaos"

# W2 对抗攻击轮（蜜罐种入 + 攻击套件；--delay 错峰缓解限流，--only 分批补测）
gauntlet run --suite suites/smoke-attacks.yaml --honeypot --label "w2-attack"

# 评测后清场（清除蜜罐文档）
gauntlet purge-honeypot
```

2. Web 控制台：浏览器访问 `http://localhost:5174`

- **Agent 评测会话**：以自然语言发起评测，四阶段流式直播（意图分析 → 测试规划 → 自主执行 → 评测结论），会话历史本地持久化
- **测试中心**：11 项评测任务卡片，悬停查看功能、关联接口、用例集与运行前置条件，点击运行并实时查看进度
- **测试历史**：轮次列表与详情抽屉，呈现判定分布、防御得分与逐用例证据
- **接口测试规划**：被测方接口清单三分类覆盖分析（直接规划 / 间接覆盖 / 范围外）

3. 运行测试

```bash
cd Backend
pytest    # 数据库依赖用例在 PostgreSQL 不可达时自动跳过
```

#### 参与贡献

1. Fork 本仓库
2. 新建 Feat_xxx 分支
3. 提交代码
4. 新建 Pull Request
