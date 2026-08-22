"""模板插件 — AI 对话。

前置配置（config.yaml）:
  adapters:
    - type: ai
      config:
        api_key: "sk-xxxx"
        base_url: "https://api.openai.com/v1"   # 可选，兼容国内 LLM
        completion_model: "gpt-4"
"""

from ncatbot.plugin import NcatBotPlugin
from ncatbot.core import registrar


class LzyPlugin(NcatBotPlugin):

    async def on_load(self):
        self.logger.info(f"{self.name} 已加载")

    async def on_close(self):
        self.logger.info(f"{self.name} 已卸载")

    @registrar.on_command("ai对话")
    async def on_ai_chat(self, event, prompt: str):
        """AI 对话：发送 'ai对话 你的问题' 获取 AI 回复。"""
        try:
            reply = await self.api.ai.chat_text(prompt)
        except Exception as e:
            reply = f"AI 调用失败: {e}"
        await event.reply(text=reply)
