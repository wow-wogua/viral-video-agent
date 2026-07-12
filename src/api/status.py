"""图结果到API状态的纯函数映射。"""


def result_status(result: dict) -> tuple[str, str]:
    termination_reason = result.get("termination_reason", "")
    if termination_reason and termination_reason != "completed":
        return "partial", termination_reason
    if result.get("report_final"):
        return "completed", termination_reason or "completed"
    if termination_reason:
        return "partial", termination_reason
    return "partial", "report_not_generated"
