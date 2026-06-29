from langgraph.checkpoint.memory import MemorySaver


def get_checkpointer():
    """返回内存版 Checkpointer。进程重启后状态丢失，生产环境建议换 Postgres。"""
    return MemorySaver()
