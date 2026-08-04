# AWS EC2 闲置停机与快速启动

适用于请求量较少时暂停 Android Unity Compare Service 的 EC2 计算资源，同时保留数据、固定 IP 和部署配置，以便未来有需求时快速恢复。

本操作只针对 `unity-compare-service` 固定实例。不要连带停止或删除 APS、S3、SSM Parameter、IAM 角色、EBS、EIP、安全组、DNS 等依赖资源。

## 停机后的资源与计费

选择 **Stop instance** 后：

- EC2 实例的计算费用停止计收。
- 实例 ID、实例配置、IAM 角色和安全组保留。
- EBS 系统盘及其中的 `/opt/app`、SQLite、Docker 数据和工作目录保留。
- EIP 保持关联，域名、AI 接口来源 IP 白名单不需要修改。
- S3 中的报告和 Litestream SQLite 灾备保留。

仍会继续产生少量费用：

- EBS 卷及快照费用。
- EIP / 公网 IPv4 地址费用，通常约 `$0.005/小时`，即约 `$3.6/月`。
- S3 存储、域名等费用。
- 如果未来购买了 Savings Plan 或 Reserved Instance，其承诺费用不会因为实例停止而暂停；当前 On-Demand 实例没有这个问题。

为了保留固定出口 IP、DNS 和 AI 白名单，不要释放 EIP。为了能原机快速恢复，不要删除 EBS 卷或 EC2 实例。

## 停止实例

### 1. 检查待处理和运行中的任务

进入 **Systems Manager → Session Manager**，连接 `unity-compare-service` 实例：

```sh
cd /opt/app
sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml \
  --env-file .env.cloud exec compare-api python -c \
  'import json, os, sqlite3; db = sqlite3.connect(os.environ["DB_PATH"]); db.row_factory = sqlite3.Row; rows = db.execute("SELECT id, status, package_name, created_at FROM tasks WHERE status IN (?, ?) ORDER BY created_at", ("queued", "running")).fetchall(); print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))'
```

输出 `[]` 表示可以安全停机。

- 存在 `running`：等待任务完成后再次检查。直接停机会中断任务；下次启动时这些任务会被标记为 `failed`，需要调用 retry 接口重新提交。
- 存在 `queued`：它们会在下次启动后自动执行。若不希望自动执行，应在停机前调用取消接口处理。

检查和点击 Stop 之间仍可能收到新任务，因此确认空闲后应尽快停机；有调用方持续提交任务时，先通知调用方暂停提交。

### 2. 检查 Litestream

确认 Litestream 容器正常且近期日志没有 S3 权限、网络或复制错误：

```sh
cd /opt/app
sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml \
  --env-file .env.cloud ps
sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml \
  --env-file .env.cloud logs --since=10m litestream
```

EC2 Stop 会正常关闭操作系统，Compose 已给 Litestream 配置 30 秒停止宽限期。不要先执行 `docker compose down`、`docker compose stop` 或手动删除容器；否则下次开机可能无法依靠重启策略自动拉起完整服务。

### 3. 在 AWS 控制台停止

1. 进入部署实例所在区域的 **EC2 → Instances**。
2. 选中名称为 `unity-compare-service` 的实例，并再次核对实例 ID。
3. 选择 **Instance state → Stop instance**。
4. 确认执行，等待实例状态变为 `Stopped`。

必须选择 **Stop instance**，不要选择 **Terminate (delete) instance**，也不要释放 EIP 或删除 EBS 卷。

### 4. 确认停机结果

- EC2 状态为 `Stopped`。
- 公网 `/health` 不再可访问，这是正常现象。
- EC2 计算费停止，但上文列出的 EBS、EIP 和 S3 等保留资源仍会计费。

## 快速启动实例

### 1. 在 AWS 控制台启动

1. 进入原部署区域的 **EC2 → Instances**。
2. 选中原 `unity-compare-service` 实例，核对实例 ID 和保留的 EIP。
3. 选择 **Instance state → Start instance**。
4. 等待状态变为 `Running`，并等待状态检查显示 `3/3 checks passed`。

通常 2～5 分钟可恢复。原 EIP 会继续使用，因此 DNS 和 AI 接口来源 IP 白名单不需要调整。

### 2. 验证服务自动恢复

先检查公网健康接口：

```sh
curl -fsS https://<域名>/health
```

预期返回：

```json
{"status":"ok"}
```

然后通过 Session Manager 进入实例，检查四个容器：

```sh
cd /opt/app
sudo systemctl is-active docker
sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml \
  --env-file .env.cloud ps
```

预期 `caddy`、`compare-api`、`compare-worker`、`litestream` 均为运行状态，Litestream 健康后才会放行 API 和 worker。

如果容器没有自动启动，手动恢复：

```sh
cd /opt/app
sudo systemctl enable --now docker
sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml \
  --env-file .env.cloud up -d
sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml \
  --env-file .env.cloud ps
```

再检查实例内健康接口和关键日志：

```sh
curl -fsS http://localhost:8080/health
sudo docker compose -f docker-compose.yml -f docker-compose.cloud.yml \
  --env-file .env.cloud logs --tail=100 caddy litestream compare-api compare-worker
```

### 3. 恢复后的注意事项

- EC2 start 不会重新执行首次部署的 user-data，也不会自动拉取停机期间的新代码或新的 SSM 参数。
- 若停机期间更新过代码或配置，启动成功后按 `CONSOLE_DEPLOY.md` 的“更新部署”步骤更新。
- 长时间停机后 Caddy 可能需要重新续签证书；只要 EIP、DNS 和 80/443 入站规则未变，Caddy 会自动处理。
- 停机前遗留的 `queued` 任务会由 worker 自动继续处理。
- 若有任务在停机时仍为 `running`，worker 启动时会把它标记为 `failed`，需调用 `POST /api/v1/tasks/{taskId}/retry` 重新提交。

## 不要做的操作

- 不要 Terminate EC2 实例。
- 不要释放 EIP，否则固定出口 IP、DNS 和 AI 白名单都要重新配置。
- 不要删除 EBS 卷、S3 桶、SSM SecureString、IAM 角色或安全组。
- 不要把停止实例误当成停止全部计费；保留资源仍会产生小额费用。
- 不要为了恢复服务新建另一台实例；优先 Start 原实例，只有原实例损坏时才按灾备流程换机重建。
