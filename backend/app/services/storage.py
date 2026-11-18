"""存储落地业务规则：状态流转、字段校验、筛选口径与去重落地清单都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "storage"
LIST_FIELDS = ["配置编号", "存储类型", "连接信息", "分区策略", "压缩格式", "保存天数", "备份副本", "清理策略"]
REQUIRED_FIELDS = ["配置编号", "存储类型", "连接信息"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用配置": "已启用", "停用配置": "已停用"}
NEGATIVE_ACTIONS = ["停用配置"]

MANIFEST_MODULE = "storage_dedup_manifest"
DATASET_MODULE = "dedup_datasets"
DETAIL_MODULE = "dedup_details"
RETAINED = "保留"

MANIFEST_FIELDS = [
    "落地编号", "配置编号", "数据集编号", "批次编号", "策略编号", "策略版本",
    "业务键", "记录编号", "记录摘要", "生成时间",
]
MANIFEST_EXPORT_FIELDS = [field for field in MANIFEST_FIELDS if field != "生成时间"]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class StorageService:
    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("配置编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"存储配置 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于存储落地可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"存储配置已{action}"

    # ------------------------------------------------------------ 去重落地清单
    def list_manifest(
        self,
        *,
        dataset_no: str | None = None,
        storage_no: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = sorted(store.rows(MANIFEST_MODULE), key=lambda row: int(row.get("id", 0)))
        if dataset_no:
            rows = [row for row in rows if _text(row.get("数据集编号")) == dataset_no]
        if storage_no:
            rows = [row for row in rows if _text(row.get("配置编号")) == storage_no]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def build_manifest(
        self,
        dataset_no: str,
        storage_no: str = "",
    ) -> tuple[list[dict[str, Any]] | None, str]:
        """消费去重明细数据集生成去重落地清单，清单只包含去重后的保留项。

        同一数据集只落一份清单；重复提交直接返回既有结果，不重新生成。
        """
        dataset_no = _text(dataset_no)
        if not dataset_no:
            return None, "缺少数据集编号，无法生成去重落地清单"
        dataset = self._find_dataset(dataset_no)
        if dataset is None:
            return None, f"去重明细数据集 {dataset_no} 不存在"

        existing = [
            row for row in store.rows(MANIFEST_MODULE)
            if _text(row.get("数据集编号")) == dataset_no
        ]
        if existing:
            return sorted(existing, key=lambda row: int(row.get("id", 0))), (
                f"去重明细数据集 {dataset_no} 已落地，存储落地拒绝生成重复结果"
            )

        retained = [
            row for row in store.rows(DETAIL_MODULE)
            if _text(row.get("数据集编号")) == dataset_no
            and _text(row.get("处理结论")) == RETAINED
        ]
        if not retained:
            return None, f"去重明细数据集 {dataset_no} 没有保留项，无法生成去重落地清单"

        next_id = max((int(row.get("id", 0)) for row in store.rows(MANIFEST_MODULE)), default=0)
        entries: list[dict[str, Any]] = []
        for offset, detail in enumerate(sorted(retained, key=lambda row: int(row.get("id", 0))), start=1):
            entries.append({
                "id": next_id + offset,
                "落地编号": f"SDM-{next_id + offset:04d}",
                "配置编号": storage_no,
                "数据集编号": dataset_no,
                "批次编号": _text(dataset.get("批次编号")),
                "策略编号": _text(dataset.get("策略编号")),
                "策略版本": _text(dataset.get("策略版本")),
                "业务键": _text(detail.get("业务键")),
                "记录编号": _text(detail.get("记录编号")),
                "记录摘要": _text(detail.get("记录摘要")),
                "生成时间": _now(),
            })
        store.rows(MANIFEST_MODULE).extend(entries)
        return entries, (
            f"去重落地清单已生成：{len(entries)} 条保留项，批次 {_text(dataset.get('批次编号'))}"
        )

    def _find_dataset(self, dataset_no: str) -> dict[str, Any] | None:
        for row in store.rows(DATASET_MODULE):
            if _text(row.get("数据集编号")) == dataset_no:
                return row
        return None
