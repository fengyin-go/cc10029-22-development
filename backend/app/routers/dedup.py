"""重复去重接口：维护去重策略，并把原始采集批次生成为去重明细数据集、重复证据与拒绝记录。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services.dedup import DATASET_EXTRA_FIELDS, LIST_FIELDS, DedupService

router = APIRouter(prefix="/api/dedup", tags=["重复去重"])

service = DedupService()

STATUSES = ["草稿", "待校验", "已启用", "已停用"]


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


def dataset_filters(request: Request) -> dict[str, str]:
    allowed = [*LIST_FIELDS, *DATASET_EXTRA_FIELDS]
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in allowed and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按策略编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、策略编号关键字与状态过滤重复去重列表。"""
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
    output.write("﻿")
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
        headers={"Content-Disposition": 'attachment; filename="dedup.csv"'})


# ---------------------------------------------------------------- 原始采集批次
@router.get("/raw-batches", response_model=PageResult[dict])
def list_raw_batches(
    keyword: str | None = Query(default=None, description="按批次编号或关联任务检索"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """业务人员查看原始采集批次：批次编号、来源站点和原始记录都在这里。"""
    items, total = service.list_raw_batches(keyword=keyword, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/raw-batches/{batch_id}", response_model=dict)
def get_raw_batch(batch_id: int) -> dict:
    """读取单个原始采集批次及其原始记录，用于核对去重前的数据。"""
    batch = service.get_raw_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"原始采集批次 {batch_id} 不存在")
    return batch


# ------------------------------------------------------------ 去重明细数据集
@router.get("/datasets", response_model=PageResult[dict])
def list_datasets(
    request: Request,
    keyword: str | None = Query(default=None, description="按数据集编号或批次编号检索"),
    status: str | None = Query(default=None, description="数据集状态"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按业务键、策略版本与状态过滤去重明细数据集。"""
    items, total = service.list_datasets(
        filters=dataset_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/datasets/export")
def export_datasets(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """导出去重明细数据集，保留业务键、相似阈值、保留顺序与策略版本。"""
    items, _ = service.list_datasets(
        filters=dataset_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    columns = [*LIST_FIELDS, *DATASET_EXTRA_FIELDS]
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
        headers={"Content-Disposition": 'attachment; filename="dedup-dataset.csv"'})


@router.post("/datasets", response_model=ActionResult)
def create_dataset(payload: dict[str, object]) -> ActionResult:
    """把原始采集批次按去重策略写入去重明细数据集；重复送交只允许补充新的重复证据。"""
    dataset, message, created = service.create_dataset(payload)
    if dataset is None:
        return ActionResult(ok=False, message=message)
    bundle = service.get_dataset_bundle(str(dataset.get("数据集编号", "")))
    entry = dict(bundle or {"dataset": dataset})
    entry["created"] = created
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/datasets/{dataset_no}", response_model=dict)
def get_dataset(dataset_no: str) -> dict:
    """返回去重明细数据集及其明细、重复证据和拒绝记录，刷新后与写入时保持一致。"""
    bundle = service.get_dataset_bundle(dataset_no)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"去重明细数据集 {dataset_no} 不存在")
    return bundle


@router.get("/details", response_model=PageResult[dict])
def list_details(
    dataset_no: str | None = Query(default=None, description="数据集编号"),
    business_key: str | None = Query(default=None, description="业务键"),
    conclusion: str | None = Query(default=None, description="保留或重复"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
) -> PageResult[dict]:
    """查看正式去重明细：每条都带保留顺序依据和策略版本。"""
    items, total = service.list_details(
        dataset_no=dataset_no, business_key=business_key, conclusion=conclusion, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/evidence", response_model=PageResult[dict])
def list_evidence(
    dataset_no: str | None = Query(default=None),
    business_key: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
) -> PageResult[dict]:
    """查看重复证据：哪条保留记录、哪条重复记录、相似度与阈值。"""
    items, total = service.list_evidence(
        dataset_no=dataset_no, business_key=business_key, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/rejections", response_model=PageResult[dict])
def list_rejections(
    dataset_no: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
) -> PageResult[dict]:
    """查看无法解释保留顺序而被挡在正式明细之外的记录及原因。"""
    items, total = service.list_rejections(dataset_no=dataset_no, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条去重策略明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"去重策略 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条去重策略，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="去重策略已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条去重策略执行提交校验、启用配置、停用配置；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
