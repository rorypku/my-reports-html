这是一个 GitUp 仓库，然后直接连接到 GitHub Pages `https://rorypku.github.io/my-reports-html/`，是我的个人主页。

使用当前的最佳实践，优雅而工程化，不要兜底，让问题暴露。

# 发布工作流

当前仓库 `rorypku/my-reports-html` 是公开展示仓库，GitHub Pages 从这里发布。不要把任何 GitHub token、SSH key、OpenAI key 或可写凭证放进 `index.html` 或任何会被 Pages 公开的静态资源里。

报告生成由本地 sitrep-agent 完成：

`/Users/kai/agent/investment_research/sitrep-agent`

现在的请求处理命令是：

```bash
codex exec -C /Users/kai/agent/investment_research/sitrep-agent "<request>"
```

# 外部请求队列

主页上的请求表单只负责跳转到私有请求仓库的 GitHub Issue 创建页：

`https://github.com/rorypku/my-reports-requests/issues/new`

`rorypku/my-reports-requests` 是 private repo，用 collaborator 权限控制谁能创建 issue。公开主页仓库 `rorypku/my-reports-html` 的 Issues 应保持关闭。

权限模型：

- 公开 Pages 任何人可能能打开，但不能直接触发本地程序。
- 只有 private repo 的 collaborator 能创建请求 issue。
- Issue 作者是实际登录 GitHub 并创建 issue 的用户，不会默认为 `rorypku`。
- 默认不使用 `REPORT_REQUEST_ALLOWED_AUTHORS` 白名单；权限由 private repo collaborators 控制。
- 如果未来需要双保险，可以在 watcher 环境变量里设置 `REPORT_REQUEST_ALLOWED_AUTHORS=rorypku,other_login`。

Issue 队列约定：

- open issue 是待处理任务。
- closed issue 是已处理或归档任务。
- watcher 只读取 open issues，不会处理 closed issues。
- 请求 issue 标题前缀是 `report request:`，例如 `report request: amazon`。
- issue body 可以只写请求文本，例如 `amazon`。

# 本地 watcher

本地 watcher 脚本：

`/Users/kai/agent/my-reports-html/scripts/process_report_requests.py`

默认读取：

`rorypku/my-reports-requests`

默认每轮最多处理 1 个 open request，成功后会 comment 并 close 对应 issue。失败时不要吞掉错误，保留失败状态和日志，让问题暴露。

手动 dry-run：

```bash
cd /Users/kai/agent/my-reports-html
uv run scripts/process_report_requests.py --dry-run
```

手动执行一轮：

```bash
cd /Users/kai/agent/my-reports-html
uv run scripts/process_report_requests.py
```

macOS `launchd` 配置：

`/Users/kai/agent/my-reports-html/scripts/com.rorypku.report-request-watcher.plist`

已安装到：

`~/Library/LaunchAgents/com.rorypku.report-request-watcher.plist`

它每 300 秒自动运行一轮 watcher。

查看日志：

```bash
tail -f ~/Library/Logs/report-request-watcher.log
tail -f ~/Library/Logs/report-request-watcher.err.log
```
