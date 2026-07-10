"""
三层兜底触发计数器
==================
追踪 LLM 输出解析的三层兜底机制各触发了多少次：
  Layer 1: JSON 解析成功
  Layer 2: 正则兜底
  Layer 3: 状态推断 / 默认值

用法:
    from src.utils.fallback_counter import fallback_counter
    fallback_counter.log("supervisor", "json")      # JSON 解析成功
    fallback_counter.log("supervisor", "regex")      # 正则兜底
    fallback_counter.log("supervisor", "inference")  # 状态推断
    summary = fallback_counter.get_summary()
"""

from contextvars import ContextVar


_records_var: ContextVar[list[dict] | None] = ContextVar("fallback_records", default=None)


class FallbackCounter:
    @staticmethod
    def _records() -> list[dict]:
        records = _records_var.get()
        if records is None:
            records = []
            _records_var.set(records)
        return records

    def log(self, agent: str, layer: str):
        """记录一次解析事件。

        Args:
            agent: Agent 名称（supervisor / researcher / analyst / writer）
            layer: 命中的层（json / regex / inference / default）
        """
        self._records().append({"agent": agent, "layer": layer})

    def get_summary(self) -> dict:
        """返回按 Agent 和层级的汇总统计。"""
        by_agent = {}
        by_layer = {"json": 0, "regex": 0, "inference": 0, "default": 0}

        records = self._records()
        for r in records:
            agent = r["agent"]
            layer = r["layer"]
            if agent not in by_agent:
                by_agent[agent] = {"json": 0, "regex": 0, "inference": 0, "default": 0, "total": 0}
            by_agent[agent][layer] = by_agent[agent].get(layer, 0) + 1
            by_agent[agent]["total"] += 1
            by_layer[layer] = by_layer.get(layer, 0) + 1

        total = len(records)
        return {
            "total": total,
            "by_layer": by_layer,
            "by_agent": by_agent,
            "json_rate": round(by_layer["json"] / total, 3) if total else 0,
            "regex_rate": round(by_layer["regex"] / total, 3) if total else 0,
            "inference_rate": round(by_layer["inference"] / total, 3) if total else 0,
        }

    def reset(self):
        _records_var.set([])


fallback_counter = FallbackCounter()
