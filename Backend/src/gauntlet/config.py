"""全局配置：从环境变量 / .env 读取。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """平台配置（对应实现计划 Task 1 接口定义）。"""

    # PostgreSQL 连接串（复用焰哨实例，独立 gauntlet schema）
    dsn: str = "postgresql://postgres:postgres@localhost:5432/fire_agent"
    # 焰哨（被测对象）服务地址与凭据
    yanshao_base_url: str = "http://127.0.0.1:8000"
    yanshao_user: str = ""
    yanshao_password: str = ""
    # run 级 token 预算熔断（spec R4）
    token_budget: int = 2_000_000
    # system prompt 哨兵串（攻击轮 LEAKED_PROMPT 检测；焰哨侧需将其注入 system prompt）
    sys_canary: str = ""
    # judge LLM（与焰哨同源 dashscope）
    judge_model: str = "qwen-max"
    # Agent 对话 LLM（与焰哨同源 dashscope，OpenAI 兼容接口）
    llm_api_key: str = ""
    llm_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen3.7-flash"
    # Agent 执行用例错峰间隔秒数（缓解被测方 dashscope 限流）
    agent_case_delay: float = 12.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GAUNTLET_",
        extra="ignore",
    )
