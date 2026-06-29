"""
Prompt 版本管理器
=================
从 prompts.yaml 加载 Prompt 模板，支持版本切换。

用法:
    from src.prompts.manager import prompt_manager

    # 获取 Prompt（自动使用当前版本）
    prompt = prompt_manager.get("supervisor", has_plan=True, data_sufficient=False, ...)

    # 获取当前版本号
    version = prompt_manager.current_version

    # 列出所有版本
    versions = prompt_manager.list_versions()
"""

import os
from pathlib import Path
from typing import Optional

import yaml


_PROMPTS_FILE = Path(__file__).parent / "prompts.yaml"


class PromptManager:
    def __init__(self, prompts_path: str = None):
        self._path = Path(prompts_path) if prompts_path else _PROMPTS_FILE
        self._data: dict = {}
        self._load()

    def _load(self):
        """加载 prompts.yaml。"""
        if not self._path.exists():
            raise FileNotFoundError(f"Prompt 配置文件不存在: {self._path}")
        with open(self._path, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f)

    @property
    def current_version(self) -> str:
        """当前 Prompt 版本。优先读环境变量 PROMPT_VERSION，否则用 yaml 中的 current_version。"""
        return os.getenv("PROMPT_VERSION", self._data.get("current_version", "v1"))

    @property
    def version_info(self) -> dict:
        """当前版本的完整信息。"""
        versions = self._data.get("versions", {})
        return versions.get(self.current_version, {})

    def get(self, agent: str, **kwargs) -> str:
        """获取指定 Agent 的 Prompt，并用 kwargs 填充模板变量。

        Args:
            agent: Agent 名称（supervisor / planner / researcher / analyst / writer_draft / writer_revision）
            **kwargs: 模板变量

        Returns:
            填充后的 Prompt 字符串
        """
        template = self.version_info.get(agent, "")
        if not template:
            raise ValueError(f"Prompt 模板不存在: agent={agent}, version={self.current_version}")
        return template.format(**kwargs)

    def get_raw(self, agent: str) -> str:
        """获取原始模板（不填充变量）。"""
        return self.version_info.get(agent, "")

    def list_versions(self) -> list[str]:
        """列出所有可用版本。"""
        return list(self._data.get("versions", {}).keys())

    def list_agents(self) -> list[str]:
        """列出当前版本中所有 Agent 的 Prompt 名称。"""
        return list(self.version_info.keys())

    def reload(self):
        """重新加载配置文件（用于热更新）。"""
        self._load()


prompt_manager = PromptManager()
