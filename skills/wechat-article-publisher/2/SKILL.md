---
name: wechat-article-publisher
description: 从 Markdown 文件或网页链接提取文章并发布到微信公众号。适用于需要“自动创建或更新草稿/提交发布”、统一微信样式（standard/viral）和批量复用发布流程的场景。
---

# WeChat Article Publisher

## 何时使用

当用户明确要求以下任一任务时触发本 skill：

- 把本地 `.md` 文章发布到微信公众号
- 把网页链接（博客/新闻页）提取后发布到微信公众号
- 更新已有公众号草稿中的某篇文章
- 需要统一微信排版模板（`standard` 或 `viral`）并自动生成封面
- 需要程序化输出 `media_id`、`publish_id`、发布状态

## 工作流

1. 准备配置：
   - 编辑本目录 `config.json`，仅需填写：`wechat.app_id`、`wechat.app_secret`、`wechat.author`
2. 安装依赖：
   - `python scripts/publish_wechat.py --install`
3. 预览（不调用微信接口）：
   - `python scripts/publish_wechat.py <输入> --dry-run`
4. 创建草稿：
   - `python scripts/publish_wechat.py <输入>`
5. 更新已有草稿中的某篇文章：
   - `python scripts/publish_wechat.py <输入> --draft-media-id <已有draft_media_id> --draft-index 0`
6. 创建或更新后直接提交发布（可选）：
   - `python scripts/publish_wechat.py <输入> --publish --status`

`<输入>` 支持：

- 本地 Markdown 文件路径
- `http://` / `https://` 网页 URL

## 命令参数

主脚本：`scripts/publish_wechat.py`

- `input`：Markdown 文件路径或网页 URL
- `--config`：配置文件路径，默认本 skill 的 `config.json`
- `--template`：覆盖模板，`standard|viral`
- `--author`：覆盖作者
- `--source-url`：覆盖原文链接
- `--draft-media-id`：传入已有草稿 `media_id`，切换为更新模式
- `--draft-index`：更新模式下要替换的文章索引，默认 `0`
- `--thumb-media-id`：直接复用已有微信封面素材 `media_id`
- `--cover-image`：指定本地封面图；更新模式下会覆盖当前草稿文章封面
- `--dry-run`：仅提取+渲染，不调微信 API；可用于本地验证更新模式参数
- `--publish`：草稿创建或更新后调用 `freepublish/submit`
- `--status`：提交发布后查询一次发布状态

## 执行约束

- 发布前优先做 `--dry-run`，检查标题、摘要和渲染 HTML。
- 更新草稿时请确认 `--draft-media-id` 来自已有草稿，`--draft-index` 指向要替换的文章位置。
- 更新模式默认会先读取现有草稿文章并保留当前 `thumb_media_id`；只有显式传入 `--thumb-media-id` 或 `--cover-image` 时才会覆盖封面。
- 如果账号无 `freepublish` 权限，`--publish` 可能返回 `48001`，此时保留草稿手动发布。
- 若创建草稿时报 `41005 media data missing`，请通过 `--cover-image` 指定封面图。
- 若显式传入 `--cover-image` 但文件不存在，脚本会直接报错而不是静默回退。

## 输出结果

脚本标准输出 JSON，关键字段：

- `operation`（`create` 或 `update`）
- `draft_media_id`
- `draft_index`（仅 `update`）
- `publish_id`（仅 `--publish`）
- `status`（仅 `--status`）
- `preview_html`（仅 `--dry-run`）
