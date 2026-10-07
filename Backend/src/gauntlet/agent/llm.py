"""Agent 对话 LLM 客户端 —— OpenAI 兼容流式接口（httpx 直连，不新增 SDK 依赖）。

与焰哨同源 dashscope compatible-mode：api_base 形如
https://dashscope.aliyuncs.com/compatible-mode/v1，密钥经 gauntlet .env 下发。
"""

import json
from collections.abc import AsyncIterator

import httpx


async def stream_chat(
    *,
    api_base: str,
    api_key: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    timeout: float = 180.0,
) -> AsyncIterator[str]:
    """流式 chat completion，逐段 yield 文本增量。

    非 200 抛 RuntimeError（带响应体片段，便于定位配额/鉴权问题）；
    仅产出 delta.content，忽略 reasoning 等其余字段。
    """
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": temperature, "stream": True}
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", "replace")
                raise RuntimeError(f"LLM 调用失败 HTTP {resp.status_code}: {body[:300]}")
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    yield delta
