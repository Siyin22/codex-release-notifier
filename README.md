# Codex CLI 正式版邮件提醒

GitHub Actions 每小时检查 openai/codex 的 Releases，通过 GraphQL 分页读取通知需要的字段（不下载附件详情）、过滤草稿和预发布，并校验正式版标签。使用工作流自动提供的 GitHub token，无需额外配置。QQ 邮箱只负责接收，无需 QQ 密码或授权码。

## 配置

1. 准备单独的 163 发件邮箱，在网页版邮箱设置中开启 SMTP，按页面要求生成客户端授权码。使用授权码而不是登录密码；服务开通条件以邮箱页面为准。
2. 将此目录上传到自己的 GitHub 公开仓库，默认分支使用 `main`。包含 `.github/workflows/notify.yml`，不要上传 `__pycache__` 或任何凭据文件。工作流使用标准的 `ubuntu-latest` 托管运行器。
3. 在仓库 Settings → Secrets and variables → Actions 中添加三个 Repository secrets：

| Secret | 内容 |
| --- | --- |
| SMTP_USER | 完整的 163 发件邮箱地址 |
| SMTP_PASSWORD | 发件邮箱的 SMTP 客户端授权码 |
| MAIL_TO | 接收通知的 QQ 邮箱地址 |

4. 默认使用 `smtp.163.com:465` 和 TLS。若使用其他支持隐式 TLS 的 SMTP 服务，设置 Repository variables `SMTP_HOST` 和 `SMTP_PORT`。
5. 在 Actions 中选择 `Codex stable release email`，点击 Run workflow。首次只记录当前正式版，不发历史邮件。后续发现新正式版时才发送邮件。
6. 在 Android QQ 邮箱 App 开启新邮件通知。检查垃圾箱；SMTP 接受邮件不代表必然投递到收件箱。

## 运行特性

- 通知进度保存到仓库 `state/releases.json`，不依赖可能过期的 Actions 缓存。
- 一次发现多个新正式版时汇总发送，按发布 ID 去重。
- 网络或 SMTP 报错不会推进进度。SMTP 已接收但响应丢失，或发信后 Git 提交失败时，下次可能重复提醒；不保证严格的恰好一次投递。
- 首次基线运行不验证 SMTP 凭据。真实收信验证需要显式触发发信；本项目尚未替你发送测试邮件。
- Actions 定时执行可能延迟。公开仓库使用标准 GitHub 托管运行器不占私有仓库的免费分钟额度；公开仓库连续 60 天没有活动可能被停用定时工作流。建议开启 GitHub Actions 失败通知，并定期确认工作流仍启用。
- 此工作流需要写入 main 分支；分支保护策略需允许工作流写入，或使用无保护的专用通知仓库。
- 云端执行不使用你电脑上的代理。不要将密码或授权码写入代码、提交到 Git 或发送到聊天。

本地测试：`python -m unittest discover -s tests -v`。测试使用模拟数据，不联网、不发邮件。
