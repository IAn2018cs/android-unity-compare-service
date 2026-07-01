# Android Unity Compare Service 项目地图

## 入口文档

- 方案和开发状态：`docs/android_unity_compare_service_plan.md`
- Git 提交规范：`docs/git_commit_convention.md`
- Agent 工作约定：`AGENTS.md`
- 参考主监控项目：`/Users/chenshuai/PycharmProjects/UnityAppVersionMonitor`
- 参考 APS 项目：`/Users/chenshuai/VSCodeProjects/android-package-service`

## 当前代码结构

```text
android-unity-compare-service/
  app/
    main.py              # FastAPI 应用入口，注册 /health、/discover、/api/v1/*
    config.py            # 环境变量配置和目录创建
    db.py                # SQLite schema、任务创建、状态更新、任务查询
    models.py            # 任务、版本、pair 状态和请求模型
    api/routes.py        # 提交/查询任务和公开 discover/home
    auth/deps.py         # 当前最小 API Key 依赖
    aps/client.py        # APS 下载 client，占位待接 worker
    worker/loop.py       # worker 主循环
    worker/executor.py   # 当前占位执行器，验证状态流转
    worker/cleanup.py    # WORK_DIR TTL 清理
    unity/dumper.py      # 轻量 Unity 包判断，占位待迁移真实 dump
  tests/test_service.py  # API、鉴权和 worker 状态流转 smoke tests
  docker-compose.yml     # compare-api + compare-worker
  Dockerfile
  pyproject.toml
```

## 已落地能力

- `GET /health`
- `GET /discover`
- `GET /`
- `POST /api/v1/unity-checks`
- `POST /api/v1/comparisons`
- `POST /api/v1/batch-comparisons`
- `GET /api/v1/tasks/{taskId}`
- SQLite 保存 `task`、`version`、`pair`、`artifact`
- worker 可领取 queued task 并跑通占位状态流转
- `AUTH_ENABLED=true` 时支持静态 `API_KEYS` 门禁

## 暂缓能力

- APS client 接入 worker 的真实包下载
- 主监控项目的 Il2Cpp dump、DummyDll compare 和报告生成迁移
- GCS/S3 报告上传和 signed URL
- 飞书 OAuth 管理后台、API Key 创建/吊销
- cancel/retry 接口

## 本地运行

```bash
python -m pytest -q
python -m uvicorn app.main:app --host 127.0.0.1 --port 18080
python -m app.worker.loop
```

## 文档维护规则

- 改接口、状态、存储、鉴权、部署或清理策略时，同步更新 `docs/android_unity_compare_service_plan.md`。
- 新增顶层模块或关键入口时，同步更新本文件。
- 写提交信息时遵守 `docs/git_commit_convention.md`。
- `AGENTS.md` 只放入口和工作约定；细节放方案文档或本地图。
