"""存储落地接口：维护存储配置，覆盖提交校验、启用配置、停用配置等动作。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services.storage import MANIFEST_EXPORT_FIELDS, StorageService

router = APIRouter(prefix="/api/storage", tags=["存储落地"])

service = StorageService()

LIST_FIELDS = ["配置编号", "存储类型", "连接信息", "分区策略", "压缩格式", "保存天数", "备份副本", "清理策略"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按配置编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、配置编号关键字与状态过滤存储落地列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="storage.csv"'})


@router.get("/manifest", response_model=PageResult[dict])
def list_manifest(
    dataset_no: str | None = Query(default=None, description="数据集编号"),
    storage_no: str | None = Query(default=None, description="配置编号"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
) -> PageResult[dict]:
    """查看去重落地清单；清单只包含去重明细数据集里的保留项。"""
    items, total = service.list_manifest(
        dataset_no=dataset_no, storage_no=storage_no, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/manifest/export")
def export_manifest(
    dataset_no: str | None = Query(default=None),
    storage_no: str | None = Query(default=None),
) -> StreamingResponse:
    """导出去重落地清单，便于业务人员核对保留项与策略版本。"""
    items, _ = service.list_manifest(
        dataset_no=dataset_no, storage_no=storage_no, page=1, size=1000000)
    columns = MANIFEST_EXPORT_FIELDS
    output = io.StringIO()
    output.write("﻿")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *columns])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in columns)]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="storage-manifest.csv"'})


@router.post("/manifest", response_model=ActionResult)
def build_manifest(payload: dict[str, object]) -> ActionResult:
    """消费去重明细数据集生成去重落地清单；同一数据集重复提交不会生成重复结果。"""
    dataset_no = str(payload.get("数据集编号") or "").strip()
    storage_no = str(payload.get("配置编号") or "").strip()
    entries, message = service.build_manifest(dataset_no, storage_no)
    if entries is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry={"items": entries})


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条存储配置明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"存储配置 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条存储配置，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="存储配置已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条存储配置执行提交校验、启用配置、停用配置；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
