# utils.py
from typing import Dict, Any

def _task_status_str(task: Dict[str, Any]) -> str:
    """
    ClickUp иногда возвращает 'status': 'open', а иногда 'status': {'status': 'open', ...}
    Эта функция-хелпер теперь здесь, чтобы избежать циклического импорта.
    """
    st = task.get("status")
    if isinstance(st, str):
        return st
    if isinstance(st, dict):
        return st.get("status") or st.get("value") or ""
    return ""
