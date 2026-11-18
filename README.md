# 智能爬虫采集平台

面向网页爬取、API接入、增量抓取、反爬对抗与采集质量校验的数据采集平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 采集目标 | `targetsite` | 目标站点 | 站点编号、站点名称、入口URL |
| 抽取规则 | `selector` | 选择器规则 | 规则编号、归属站点、列表选择器 |
| 爬虫引擎 | `crawler` | 爬虫任务 | 任务编号、任务名称、关联站点 |
| 代理池 | `proxy` | 代理节点 | 节点编号、IP地址、端口号 |
| 反爬对抗 | `antiblock` | 反爬策略 | 策略编号、策略名称、触发条件 |
| 定时调度 | `schedule` | 调度计划 | 计划编号、关联任务、Cron表达式 |
| 数据提取 | `extractor` | 提取模板 | 模板编号、模板名称、输入URL |
| 采集校验 | `validate` | 校验规则 | 规则编号、校验字段、期望格式 |
| 失败重试 | `retry` | 重试策略 | 策略编号、适用任务、最大重试 |
| 存储落地 | `storage` | 存储配置 | 配置编号、存储类型、连接信息 |
| 重复去重 | `dedup` | 去重策略 | 策略编号、业务键列、去重算法 || 质量报告 | `quality` | 质量指标 | 指标编号、指标名称、统计口径 |
| 运行监控 | `monitor` | 监控大盘 | 大盘编号、关联任务、采集速率 |
| 告警中心 | `alert` | 告警规则 | 规则编号、监控对象、告警条件 |
| 采集API | `apigate` | API配置 | 配置编号、端点路径、请求方法 |
| 历史归档 | `archive` | 归档策略 | 策略编号、数据来源、归档周期 |
| 模板市场 | `template` | 采集模板 | 模板编号、模板名称、适用站点 |
| 采集流程 | `flowline` | 流程编排 | 流程编号、流程名称、步骤序列 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 去重明细数据集与去重落地清单

重复去重除了维护去重策略，还把原始采集批次按策略生成“去重明细数据集”，并长期保留去重依据：

- 原始采集批次：`GET /api/dedup/raw-batches`、`GET /api/dedup/raw-batches/{id}`。
- 生成数据集：`POST /api/dedup/datasets`，提交 `策略编号` 与 `批次编号`，可覆盖 `相似阈值`、`保留顺序`。
  数据集同时写入业务键列、相似阈值、保留顺序和策略版本；无法解释保留顺序的记录写入拒绝记录，
  不进入正式明细。
- 查看数据集：`GET /api/dedup/datasets`、`GET /api/dedup/datasets/{数据集编号}`，
  同时返回去重明细（`处理结论` 为保留/重复）、重复证据和拒绝记录。
- 同一策略 + 批次只保留一份已确认数据集：重复送交不会新增数据集，只允许通过 `重复证据`
  补充新出现的证据，已确认的保留记录与策略版本不变；相似阈值导致同一业务键保留对象变化时，
  冲突版本会被拒绝，下游始终只有一份带策略依据的去重明细。
- 存储落地消费数据集生成去重落地清单：`POST /api/storage/manifest`（`数据集编号`、可选 `配置编号`），
  清单只包含 `处理结论=保留` 的记录；同一数据集重复提交不会生成重复结果，
  `GET /api/storage/manifest` 查看，刷新后结果保持一致。

重复去重沿用的既有字段名不变，数据集新增字段只追加在既有字段之后。

领域：数据工程
子方向：数据采集、爬虫与RPA
