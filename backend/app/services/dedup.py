"""重复去重业务规则：策略流转、去重明细数据集、重复证据与去重依据都收在这里。

去重明细数据集是“原始采集批次 -> 按去重策略判定 -> 正式去重明细”的落点：
- 数据集必须同时写入业务键、相似阈值、保留顺序和策略版本；
- 只有能解释保留顺序的记录才进入正式明细，其余记录进入拒绝记录；
- 同一策略 + 批次只允许一份已确认的数据集，重复导入只能补充新的重复证据；
- 相同业务键在相似阈值下给出不同保留对象时，拒绝冲突版本，保证下游只有一份策略依据。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

from app.store import store

MODULE = "dedup"
LIST_FIELDS = ["策略编号", "业务键列", "去重算法", "对比窗口", "相似阈值", "保留顺序", "增量模式", "生效批次"]
REQUIRED_FIELDS = ["策略编号", "业务键列", "去重算法"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用配置": "已启用", "停用配置": "已停用"}
NEGATIVE_ACTIONS = ["停用配置"]

RAW_MODULE = "dedup_raw_batches"
DATASET_MODULE = "dedup_datasets"
DETAIL_MODULE = "dedup_details"
EVIDENCE_MODULE = "dedup_evidence"
REJECTION_MODULE = "dedup_rejections"

DATASET_STATUS = "已确认"
RETAINED = "保留"
DUPLICATE = "重复"

# 新增字段只追加在既有字段之后，不覆盖重复去重已有的字段名。
DATASET_EXTRA_FIELDS = [
    "数据集编号", "批次编号", "策略版本", "状态", "记录总数", "保留数量",
    "重复数量", "拒绝数量", "重复证据数", "业务键数", "生成时间",
]
DETAIL_EXTRA_FIELDS = [
    "数据集编号", "批次编号", "策略版本", "业务键", "记录编号", "记录摘要",
    "相似度", "处理结论", "保留顺序依据", "生成时间",
]
EVIDENCE_EXTRA_FIELDS = [
    "数据集编号", "策略编号", "策略版本", "业务键", "保留记录编号", "重复记录编号",
    "相似度", "相似阈值", "证据说明", "生成时间",
]
REJECTION_FIELDS = [
    "数据集编号", "策略编号", "批次编号", "业务键", "记录编号", "原因", "生成时间",
]

ORDER_PATTERN = re.compile(r"^(?P<field>.+?)(?P<direction>升序|降序)$")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _next_id(module: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(module)), default=0) + 1


def _next_code(module: str, field: str, prefix: str) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    numbers = [
        int(match.group(1))
        for row in store.rows(module)
        if (match := pattern.match(_text(row.get(field))))
    ]
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"


def _parse_order(order: str) -> tuple[str, bool] | None:
    match = ORDER_PATTERN.match(order.strip())
    if not match:
        return None
    return match.group("field").strip(), match.group("direction") == "升序"


def _is_exact_algorithm(algorithm: str) -> bool:
    return any(token in algorithm for token in ("精确", "完全", "一致"))


def _record_content(record: dict[str, Any]) -> str:
    return _text(record.get("内容摘要") or record.get("内容指纹") or record.get("内容"))


class DedupService:
    # ------------------------------------------------------------------ 策略
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
            rows = [row for row in rows if keyword.casefold() in str(row.get("策略编号", "")).casefold()]
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
            return None, f"去重策略 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于重复去重可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"去重策略已{action}"

    # ------------------------------------------------------------ 原始采集批次
    def list_raw_batches(
        self,
        *,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(RAW_MODULE)
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)))
        if keyword:
            lowered = keyword.casefold()
            rows = [
                row for row in rows
                if lowered in str(row.get("批次编号", "")).casefold()
                or lowered in str(row.get("关联任务", "")).casefold()
            ]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_raw_batch(self, batch_id: int) -> dict[str, Any] | None:
        return store.find(RAW_MODULE, batch_id)

    def find_raw_batch(self, batch_no: str) -> dict[str, Any] | None:
        for row in store.rows(RAW_MODULE):
            if _text(row.get("批次编号")) == batch_no:
                return row
        return None

    # ------------------------------------------------------------ 数据集查询
    def list_datasets(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = sorted(store.rows(DATASET_MODULE), key=lambda row: int(row.get("id", 0)))
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in _text(row.get(field)).casefold()]
        if keyword:
            lowered = keyword.casefold()
            rows = [
                row for row in rows
                if lowered in _text(row.get("数据集编号")).casefold()
                or lowered in _text(row.get("批次编号")).casefold()
            ]
        if status:
            rows = [row for row in rows if _text(row.get("状态")) == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_dataset(self, dataset_no: str) -> dict[str, Any] | None:
        for row in store.rows(DATASET_MODULE):
            if _text(row.get("数据集编号")) == dataset_no:
                return row
        return None

    def get_dataset_bundle(self, dataset_no: str) -> dict[str, Any] | None:
        dataset = self.get_dataset(dataset_no)
        if dataset is None:
            return None
        return {
            "dataset": dataset,
            "details": self._rows_for_dataset(DETAIL_MODULE, dataset_no, "id"),
            "evidence": self._rows_for_dataset(EVIDENCE_MODULE, dataset_no, "id"),
            "rejections": self._rows_for_dataset(REJECTION_MODULE, dataset_no, "id"),
        }

    def _rows_for_dataset(self, module: str, dataset_no: str, order_field: str) -> list[dict[str, Any]]:
        rows = [row for row in store.rows(module) if _text(row.get("数据集编号")) == dataset_no]
        return sorted(rows, key=lambda row: int(row.get(order_field, 0)))

    def list_details(
        self,
        *,
        dataset_no: str | None = None,
        business_key: str | None = None,
        conclusion: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = sorted(store.rows(DETAIL_MODULE), key=lambda row: int(row.get("id", 0)))
        if dataset_no:
            rows = [row for row in rows if _text(row.get("数据集编号")) == dataset_no]
        if business_key:
            lowered = business_key.casefold()
            rows = [row for row in rows if lowered in _text(row.get("业务键")).casefold()]
        if conclusion:
            rows = [row for row in rows if _text(row.get("处理结论")) == conclusion]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def list_evidence(
        self,
        *,
        dataset_no: str | None = None,
        business_key: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = sorted(store.rows(EVIDENCE_MODULE), key=lambda row: int(row.get("id", 0)))
        if dataset_no:
            rows = [row for row in rows if _text(row.get("数据集编号")) == dataset_no]
        if business_key:
            lowered = business_key.casefold()
            rows = [row for row in rows if lowered in _text(row.get("业务键")).casefold()]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def list_rejections(
        self,
        *,
        dataset_no: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = sorted(store.rows(REJECTION_MODULE), key=lambda row: int(row.get("id", 0)))
        if dataset_no:
            rows = [row for row in rows if _text(row.get("数据集编号")) == dataset_no]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    # ------------------------------------------------------------ 数据集生成
    def create_dataset(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        """按去重策略把原始采集批次写入去重明细数据集。

        返回 (数据集, 说明, 是否新增写入)。重复送交不会新增数据集；
        只有同一批次新出现的重复证据允许追加，已确认的保留记录保持不变。
        """
        policy_no = _text(values.get("策略编号"))
        batch_no = _text(values.get("批次编号"))
        if not policy_no:
            return None, "缺少策略编号，无法确定去重依据", False
        if not batch_no:
            return None, "缺少批次编号，无法读取原始采集批次", False

        policy = self._find_policy(policy_no)
        if policy is None:
            return None, f"去重策略 {policy_no} 不存在或已归档", False
        batch = self.find_raw_batch(batch_no)
        if batch is None:
            return None, f"原始采集批次 {batch_no} 不存在", False

        key_column = _text(values.get("业务键列") or policy.get("业务键列"))
        if not key_column:
            return None, "去重策略缺少业务键列，去重明细数据集必须同时写入业务键", False

        algorithm = _text(policy.get("去重算法")) or "相似度去重"
        threshold_raw = values.get("相似阈值", policy.get("相似阈值"))
        threshold = _number(threshold_raw)
        if threshold is None or threshold < 0 or threshold > 1:
            return None, f"相似阈值「{threshold_raw}」无效，无法生成可解释的去重明细", False

        order = _text(values.get("保留顺序") or policy.get("保留顺序"))
        parsed_order = _parse_order(order)
        if parsed_order is None:
            return None, f"保留顺序「{order}」无法解析，不能进入正式去重明细", False
        order_field, ascending = parsed_order

        effective_batch = _text(policy.get("生效批次")) or batch_no
        version = (
            f"{policy_no}@{effective_batch}@{key_column}"
            f"@T{_format_number(threshold)}@{order}"
        )

        records = self._raw_records(batch)
        if not records:
            return None, f"原始采集批次 {batch_no} 没有可去重的记录", False

        next_id = _next_id(DATASET_MODULE)
        dataset_no = _next_code(DATASET_MODULE, "数据集编号", "DDS")
        result = self._evaluate(
            records=records,
            dataset_no=dataset_no,
            batch_no=batch_no,
            policy_no=policy_no,
            key_column=key_column,
            algorithm=algorithm,
            threshold=threshold,
            order=order,
            order_field=order_field,
            ascending=ascending,
            version=version,
        )
        details = result["details"]
        evidence = result["evidence"]
        rejections = result["rejections"]
        retained_map = result["retained_map"]

        if not details:
            existing = self._find_dataset(policy_no, batch_no)
            existing_no = _text(existing.get("数据集编号")) if existing else ""
            self._append_rejections(
                {**row, "数据集编号": existing_no} for row in rejections
            )
            return None, "没有可解释保留顺序的记录，未生成正式去重明细", False

        existing = self._find_dataset(policy_no, batch_no)
        conflict = self._find_conflict(batch_no, existing, retained_map)
        if conflict is not None:
            other, conflict_key = conflict
            other_version = _text(other.get("策略版本"))
            store.rows(REJECTION_MODULE).append({
                "id": _next_id(REJECTION_MODULE),
                "数据集编号": _text(other.get("数据集编号")),
                "策略编号": policy_no,
                "批次编号": batch_no,
                "业务键": conflict_key,
                "记录编号": "",
                "原因": (
                    f"相似阈值 {_format_number(threshold)} 对业务键 {conflict_key} "
                    f"给出不同保留对象，已存在策略版本 {other_version}，"
                    "下游只保留一份带策略依据的去重明细版本"
                ),
                "生成时间": _now(),
            })
            return None, (
                f"去重明细数据集冲突：业务键 {conflict_key} 在相似阈值 "
                f"{_format_number(threshold)} 下的保留对象与已确认版本 "
                f"{_text(other.get('数据集编号'))}（策略版本 {other_version}）不一致，"
                "拒绝写入冲突版本"
            ), False

        if existing is not None:
            new_evidence = self._merge_evidence(existing, values.get("重复证据"), retained_map)
            if new_evidence:
                existing["重复证据数"] = int(existing.get("重复证据数", 0)) + new_evidence
                return existing, (
                    f"已为批次 {batch_no} 补充 {new_evidence} 条新出现的重复证据，"
                    "已确认的保留记录和策略版本未变化"
                ), False
            return existing, (
                f"去重明细数据集 {_text(existing.get('数据集编号'))} 已存在，"
                "重复去重拒绝重复写入"
            ), False

        dataset = {
            "id": next_id,
            "策略编号": policy_no,
            "业务键列": key_column,
            "去重算法": algorithm,
            "对比窗口": policy.get("对比窗口"),
            "相似阈值": _format_number(threshold),
            "保留顺序": order,
            "增量模式": policy.get("增量模式"),
            "生效批次": effective_batch,
            "数据集编号": dataset_no,
            "批次编号": batch_no,
            "策略版本": version,
            "状态": DATASET_STATUS,
            "记录总数": len(records),
            "保留数量": len([row for row in details if row["处理结论"] == RETAINED]),
            "重复数量": len([row for row in details if row["处理结论"] == DUPLICATE]),
            "拒绝数量": len(rejections),
            "重复证据数": len(evidence),
            "业务键数": len(retained_map),
            "生成时间": _now(),
        }
        store.rows(DATASET_MODULE).append(dataset)
        self._append_rejections(rejections)
        store.rows(DETAIL_MODULE).extend(
            {**row, "id": _next_id(DETAIL_MODULE) + index}
            for index, row in enumerate(details)
        )
        store.rows(EVIDENCE_MODULE).extend(
            {**row, "id": _next_id(EVIDENCE_MODULE) + index}
            for index, row in enumerate(evidence)
        )
        batch["状态"] = "已去重"
        return dataset, (
            f"已生成去重明细数据集 {dataset_no}：保留 {dataset['保留数量']} 条，"
            f"重复 {dataset['重复数量']} 条，拒绝 {dataset['拒绝数量']} 条"
        ), True

    def _find_policy(self, policy_no: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if _text(row.get("策略编号")) == policy_no:
                return row
        return None

    def _find_dataset(self, policy_no: str, batch_no: str) -> dict[str, Any] | None:
        for row in store.rows(DATASET_MODULE):
            if _text(row.get("策略编号")) == policy_no and _text(row.get("批次编号")) == batch_no:
                return row
        return None

    def _raw_records(self, batch: dict[str, Any]) -> list[dict[str, Any]]:
        records = batch.get("原始记录")
        if not isinstance(records, list):
            return []
        return [dict(record) for record in records if isinstance(record, dict)]

    def _retained_map(self, dataset_no: str) -> dict[str, list[str]]:
        retained: dict[str, list[str]] = {}
        for row in store.rows(DETAIL_MODULE):
            if _text(row.get("数据集编号")) != dataset_no:
                continue
            if _text(row.get("处理结论")) != RETAINED:
                continue
            retained.setdefault(_text(row.get("业务键")), []).append(_text(row.get("记录编号")))
        return retained

    def _find_conflict(
        self,
        batch_no: str,
        existing: dict[str, Any] | None,
        retained_map: dict[str, list[str]],
    ) -> tuple[dict[str, Any], str] | None:
        """同一批次、同一业务键列下，已确认版本的保留对象必须与新版本一致。

        不一致说明相似阈值给出了不同保留对象，下游不允许出现两份策略依据。
        """
        key_column = _text((existing or {}).get("业务键列"))
        for dataset in store.rows(DATASET_MODULE):
            if _text(dataset.get("批次编号")) != batch_no:
                continue
            if key_column and _text(dataset.get("业务键列")) != key_column:
                continue
            existing_map = self._retained_map(_text(dataset.get("数据集编号")))
            conflict_key = self._conflict_key(existing_map, retained_map)
            if conflict_key is not None:
                return dataset, conflict_key
        return None

    def _conflict_key(
        self,
        left: dict[str, list[str]],
        right: dict[str, list[str]],
    ) -> str | None:
        for key, records in right.items():
            if set(left.get(key, [])) != set(records):
                return key
        for key in left:
            if key not in right:
                return key
        return None

    def _merge_evidence(
        self,
        dataset: dict[str, Any],
        evidence_payload: Any,
        retained_map: dict[str, list[str]],
    ) -> int:
        """重复导入只补充新出现的重复证据，永远不改写已确认的保留记录。"""
        if not isinstance(evidence_payload, list):
            return 0
        dataset_no = _text(dataset.get("数据集编号"))
        existing_keys = {
            (
                _text(row.get("业务键")),
                _text(row.get("保留记录编号")),
                _text(row.get("重复记录编号")),
            )
            for row in store.rows(EVIDENCE_MODULE)
            if _text(row.get("数据集编号")) == dataset_no
        }
        added = 0
        for item in evidence_payload:
            if not isinstance(item, dict):
                continue
            business_key = _text(item.get("业务键"))
            retained_record = _text(item.get("保留记录编号"))
            duplicate_record = _text(item.get("重复记录编号"))
            if not business_key or not duplicate_record:
                continue
            if retained_record not in retained_map.get(business_key, []):
                continue
            key = (business_key, retained_record, duplicate_record)
            if key in existing_keys:
                continue
            similarity = _number(item.get("相似度"))
            store.rows(EVIDENCE_MODULE).append({
                "id": _next_id(EVIDENCE_MODULE),
                "数据集编号": dataset_no,
                "策略编号": _text(dataset.get("策略编号")),
                "策略版本": _text(dataset.get("策略版本")),
                "业务键": business_key,
                "保留记录编号": retained_record,
                "重复记录编号": duplicate_record,
                "相似度": _format_number(similarity) if similarity is not None else _text(item.get("相似度")),
                "相似阈值": _text(dataset.get("相似阈值")),
                "证据说明": _text(item.get("证据说明"))
                or f"重复导入补充：{duplicate_record} 是保留记录 {retained_record} 的重复证据",
                "生成时间": _now(),
            })
            existing_keys.add(key)
            added += 1
        return added

    def _append_rejections(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            store.rows(REJECTION_MODULE).append({**row, "id": _next_id(REJECTION_MODULE)})

    def _evaluate(
        self,
        *,
        records: list[dict[str, Any]],
        dataset_no: str,
        batch_no: str,
        policy_no: str,
        key_column: str,
        algorithm: str,
        threshold: float,
        order: str,
        order_field: str,
        ascending: bool,
        version: str,
    ) -> dict[str, Any]:
        """按业务键分组，按保留顺序逐条判定，只有可解释的记录进入正式明细。"""
        groups: dict[str, list[dict[str, Any]]] = {}
        rejections: list[dict[str, Any]] = []
        for record in records:
            record_no = _text(record.get("记录编号"))
            business_key = _text(record.get(key_column))
            if not record_no:
                rejections.append(self._rejection(
                    dataset_no, policy_no, batch_no, business_key, "", "缺少记录编号，无法写入去重明细"))
                continue
            if not business_key:
                rejections.append(self._rejection(
                    dataset_no, policy_no, batch_no, "", record_no,
                    f"缺少业务键 {key_column}，无法解释保留顺序"))
                continue
            groups.setdefault(business_key, []).append(record)

        exact = _is_exact_algorithm(algorithm)
        details: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        retained_map: dict[str, list[str]] = {}

        for business_key, group in groups.items():
            missing_field = [record for record in group if order_field not in record]
            if missing_field:
                for record in group:
                    rejections.append(self._rejection(
                        dataset_no, policy_no, batch_no, business_key,
                        _text(record.get("记录编号")),
                        f"保留顺序字段 {order_field} 缺失，无法解释保留顺序"))
                continue

            ordered = sorted(
                group,
                key=lambda record: (
                    _text(record.get(order_field)),
                    _text(record.get("记录编号")),
                ),
                reverse=not ascending,
            )
            anchors: list[tuple[dict[str, Any], float | None]] = []
            for record in ordered:
                record_no = _text(record.get("记录编号"))
                similarity = self._similarity(record, exact)
                if similarity is None:
                    rejections.append(self._rejection(
                        dataset_no, policy_no, batch_no, business_key, record_no,
                        "缺少可用的相似度，无法判定是否为重复记录"))
                    continue

                matched: tuple[dict[str, Any], float | None] | None = None
                for anchor, _ in anchors:
                    similarity_to_anchor = self._similarity_to(record, anchor, exact)
                    if similarity_to_anchor is None:
                        continue
                    if similarity_to_anchor >= threshold:
                        matched = (anchor, similarity_to_anchor)
                        break

                if matched is not None:
                    anchor, similarity_to_anchor = matched
                    anchor_no = _text(anchor.get("记录编号"))
                    basis = (
                        f"{order}：与保留记录 {anchor_no} 的相似度 "
                        f"{_format_number(similarity_to_anchor)} ≥ 阈值 {_format_number(threshold)}"
                    )
                    details.append(self._detail(
                        dataset_no, policy_no, batch_no, version, business_key,
                        record, similarity, DUPLICATE, basis))
                    evidence.append({
                        "数据集编号": dataset_no,
                        "策略编号": policy_no,
                        "策略版本": version,
                        "业务键": business_key,
                        "保留记录编号": anchor_no,
                        "重复记录编号": record_no,
                        "相似度": _format_number(similarity_to_anchor),
                        "相似阈值": _format_number(threshold),
                        "证据说明": (
                            f"相似度 {_format_number(similarity_to_anchor)} ≥ 阈值 "
                            f"{_format_number(threshold)}，判定为保留记录 {anchor_no} 的重复记录"
                        ),
                        "生成时间": _now(),
                    })
                else:
                    if anchors:
                        basis = (
                            f"{order}：相似度 {_format_number(similarity)} < 阈值 "
                            f"{_format_number(threshold)}，未命中已保留记录，作为新的保留项"
                        )
                    else:
                        basis = f"{order}：业务键 {business_key} 的首个保留项"
                    details.append(self._detail(
                        dataset_no, policy_no, batch_no, version, business_key,
                        record, similarity, RETAINED, basis))
                    anchors.append((record, similarity))
                    retained_map.setdefault(business_key, []).append(record_no)

        return {
            "details": details,
            "evidence": evidence,
            "rejections": rejections,
            "retained_map": retained_map,
        }

    def _detail(
        self,
        dataset_no: str,
        policy_no: str,
        batch_no: str,
        version: str,
        business_key: str,
        record: dict[str, Any],
        similarity: float | None,
        conclusion: str,
        basis: str,
    ) -> dict[str, Any]:
        return {
            "数据集编号": dataset_no,
            "策略编号": policy_no,
            "批次编号": batch_no,
            "策略版本": version,
            "业务键": business_key,
            "记录编号": _text(record.get("记录编号")),
            "记录摘要": _text(record.get("内容摘要") or record.get("内容指纹")),
            "相似度": _format_number(similarity),
            "处理结论": conclusion,
            "保留顺序依据": basis,
            "生成时间": _now(),
        }

    def _rejection(
        self,
        dataset_no: str,
        policy_no: str,
        batch_no: str,
        business_key: str,
        record_no: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "数据集编号": dataset_no,
            "策略编号": policy_no,
            "批次编号": batch_no,
            "业务键": business_key,
            "记录编号": record_no,
            "原因": reason,
            "生成时间": _now(),
        }

    def _similarity(self, record: dict[str, Any], exact: bool) -> float | None:
        if exact:
            return 1.0
        return _number(record.get("相似度"))

    def _similarity_to(
        self,
        record: dict[str, Any],
        anchor: dict[str, Any],
        exact: bool,
    ) -> float | None:
        if exact:
            return 1.0 if _record_content(record) == _record_content(anchor) else 0.0
        return _number(record.get("相似度"))
