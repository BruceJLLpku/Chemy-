# 账户、收藏与组卷历史启用

网站继续使用正式仓库和 GitHub Pages。Supabase 提供邮箱注册、登录、验证邮件、密码找回和个人数据库；不需要把题库迁到数据库。

## 首次配置

1. 在 https://supabase.com/dashboard 创建归站点所有者管理的项目。
2. 在 SQL Editor 执行 `supabase/001_accounts.sql`（仅执行一次）。脚本启用行级权限；每个登录用户只能读取、添加和删除自己的记录，匿名访问没有权限。
3. 在 Authentication → URL Configuration 将 Site URL 设为 `https://chemygroup.github.io/Chemy-website-official/`，并将这个完整地址加入 Redirect URLs。本地测试时另加入实际本地地址。
4. 在邮箱登录设置中开启邮箱注册和邮箱验证，密码最少设为 8 位。
5. 为公开注册配置自己的 SMTP 发信服务，测试验证邮件和找回密码邮件能送达。内置测试邮件服务不适合作为对公众开放注册的正式发信服务。按实际流量配置 Auth 限流及监控。
6. 在 `dist/account-config.json` 填入项目 URL 和 publishable key（也可用 legacy anon key）。这两项为浏览器公开连接信息。绝对不要填 secret key、service_role key、数据库密码或 SMTP 密码。
7. 本地预览并完成下方验收后，将本次文件推送到正式仓库 main，现有 Pages 工作流会发布。

```json
{"url":"https://YOUR_PROJECT.supabase.co","publishableKey":"YOUR_PUBLIC_KEY"}
```

## 使用

- 顶部“登录 / 我的题库”注册或登录。验证邮件返回本站后自动识别登录状态。
- 普通题目和 AI 练习题都可收藏，个人中心可跳转原题、取消收藏。
- 登录后成功下载自选或 AI 练习卷，自动保存该卷题目清单。也可在个人中心保存当前勾选题目，或在 AI 结果中点击保存。
- 历史按时间倒序，每批 50 条，支持继续加载、恢复选题、重新下载和删除。
- 历史保存当时的题目 ID 与顺序，不保存 PDF、AI 关联说明或题目正文快照；下载使用当前题库原题。恢复后使用原有下载功能，下载顺序遵循该功能的专题排序规则。
- 未登录仍可以查题和组卷。未配置后台时账户入口会明确提示服务尚未启用。
- 会话由 Supabase SDK 管理；退出后清空页面上的个人数据。共享电脑使用完应退出账户。

## 上线前验收（需要真实项目）

- 用两个邮箱注册并验证，分别登录、刷新、退出、再次登录；检查找回密码邮件与新密码登录。
- A 收藏题目和保存卷，B 看不到 A 的数据；未登录不能查询表。
- 使用 A 的登录 token 直接调用 REST API，尝试读、写、删除 B 的记录，确认数据库权限拒绝或返回空记录。
- 手机或另一浏览器登录 A，检查收藏和历史同步；网络断开时显示失败，恢复后可重试。
- AI 组卷、自选题目下载后出现历史；恢复历史可重新导出题目与答案。

## 依赖与维护

账户模块仅在后台配置有效时加载固定版本 `@supabase/supabase-js@2.57.4`，来源为 jsDelivr ESM。需实际验证主要访客网络能访问该 CDN 和项目服务。题库与下载功能不依赖账户模块。

数据库迁移尚未在真实 Supabase 项目执行；本地浏览器测试不能替代真实鉴权、邮件和数据库权限验收。

官方参考：https://supabase.com/docs/guides/auth/passwords 、https://supabase.com/docs/guides/database/postgres/row-level-security 、https://supabase.com/docs/guides/auth/auth-smtp
