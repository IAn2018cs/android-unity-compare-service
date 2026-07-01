# Git Commit 规范

提交信息使用中文，格式参考 Conventional Commits：

```text
<type>(<scope>): <中文简短说明>

<中文正文，可选>

<footer，可选>
```

## 基本规则

- `type` 使用英文小写，`scope` 可选，说明本次提交影响的模块。
- 简短说明使用中文，控制在 50 个中文字符以内，不以句号结尾。
- 一个 commit 只做一件事，避免把无关修改混在一起。
- 需要说明背景、取舍、风险时写正文；正文用中文描述“为什么改”和“影响什么”。
- 关联需求或缺陷时写在 footer，例如 `Closes #123`。
- 破坏兼容时必须写 `BREAKING CHANGE: <中文说明>`。

## 常用 type

| type | 使用场景 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 文档修改 |
| `style` | 代码格式、空白、命名等不影响逻辑的修改 |
| `refactor` | 重构，不新增功能也不修复缺陷 |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `build` | 构建系统、依赖、打包配置 |
| `ci` | CI/CD 配置 |
| `chore` | 维护性杂项 |
| `revert` | 回滚提交 |

## 本项目常用 scope

| scope | 使用场景 |
| --- | --- |
| `api` | FastAPI 路由、请求/响应契约 |
| `auth` | API Key、飞书 OAuth、会话管理 |
| `db` | SQLite schema、任务状态存取 |
| `aps` | Android Package Service client |
| `worker` | 后台任务领取、执行和清理 |
| `unity` | Unity dump、DummyDll compare、报告生成 |
| `storage` | 报告上传和 signed URL |
| `deploy` | Docker、Compose、运行参数 |
| `docs` | 文档和项目地图 |

## 示例

```text
feat(api): 增加批量相邻版本对比任务
fix(worker): 修复失败任务未清理工作目录
docs: 增加 Git Commit 规范
refactor(db): 简化任务状态查询结构
test(api): 补充任务提交 smoke test
build(deploy): 增加 compare-worker compose 服务
```

带正文的示例：

```text
fix(worker): 修复 XAPK dump 失败后任务卡住

失败分支只更新了 version 状态，没有汇总 pair 和 task。
现在统一在异常出口写入失败状态，并按 KEEP_FAILED_WORK_DIR 决定是否保留现场。

Closes #123
```
