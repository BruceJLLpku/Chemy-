# 题目论坛维护

## 已实现

- 正常专题页和收藏页的每道题下展示最近三条讨论，含类型、标题、摘要、作者、认证和回复数。
- “查看全部”按 20 条分页。帖子详情按时间阅读回复，每次再加载 50 条；可指定回复某个人，不无限嵌套。
- 左侧“题目讨论”按最近发帖/回复汇总题目，每道题只占一行，支持专题、未解决提问及团队参与筛选。编辑旧帖不提升活动时间。
- 提问和交流两类帖子。提问者或管理员可以采纳回复，也可以重新打开问题。团队回答不自动视为标准答案。
- 所有访客可阅读；注册并验证邮箱后设置昵称、发帖和回复。公开资料不含邮箱。
- 基础 Markdown：粗体、斜体、代码、列表、引用。正文作为转义后的文本渲染，不接收原始 HTML；公式通过固定版本 KaTeX 0.19.1 渲染，trust=false。
- 图片为 PNG/JPEG/WebP，每条最多 3 张、每张最多 5 MB，私有 Storage bucket；只能引用本人上传的真实对象。可见帖子的附图可申请短时访问链接，隐藏/删除后不能再公开申请链接。
- 回复、指定回复和采纳会产生站内消息；只允许接收者读取/标记已读。登录后每分钟检查未读数，也可直接打开消息页。不发送邮件。
- 管理员按昵称查找用户，授予/撤销“Chemy 团队成员”、禁言/解禁、隐藏/恢复帖子和回复、关闭/开放讨论，并留存管理记录。没有授予更多管理员的前端/API 功能。
- 用户可编辑/删除自己的发言；删除原帖保留已有回复，删除被采纳回复自动清除解决状态。
- 组卷历史移动到左侧独立页面，保留恢复选题、再次下载、删除和加载更多；账户弹窗只保留登录及账户设置。

## 首次数据库配置

在 Supabase SQL Editor 按顺序执行一次：

1. 已有账户表 `001_accounts.sql`（已执行过的项目不要重复执行）。
2. `002_forum.sql`：表、索引、RLS、数据库操作函数、最近题目视图和图片 bucket/权限。
3. `003_question_registry.sql`：目前 1933 道题的稳定 ID、专题、题名与专题编号。
4. 通过数据库管理员在可信 SQL Editor 中初始化唯一管理员，示例：

```sql
do $$
declare account_id uuid;
begin
 select id into account_id from auth.users where lower(email)=lower('替换成已经注册的网站邮箱');
 if account_id is null then raise exception '请先注册网站账号'; end if;
 insert into public.forum_profiles(user_id,display_name,is_admin,is_team)
 values(account_id,'Chemy 管理员',true,true)
 on conflict(user_id) do update set is_admin=true,is_team=true;
end $$;
```

当前项目的一次性合并配置脚本保存在本地临时目录，含站点所有者提供的邮箱，不提交至公共仓库。

新增或重新编号题目时，更新 registry SQL 并执行 upsert；不要以可变的专题题号作为讨论关联键。正文仍从原有题库加载。

## 权限边界

浏览器只使用现有 publishable key。认证和管理员字段保存在受保护的 `forum_profiles` 中；浏览器对所有论坛表均无直接写权限。所有写操作都经过 `forum_action`，校验当前账号、邮箱验证、禁言、内容所有者、讨论关闭状态和管理员权限。用户可修改的 Auth metadata 不参与角色判断。

`forum_action` 和权限帮助函数固定空 search_path；数据库表均开启 RLS，最近讨论视图使用 security_invoker。隐藏的主帖及回复无法被匿名查询，私有通知只能由接收人查询。图片读取也检查帖子可见性；已签发链接有效期 60 秒。

普通帖子与回复合计每账号每分钟最多 10 条，数据库事务锁防止并发绕过。昵称和帖子长度、图片数量、跨帖子回复引用、采纳目标等由数据库重复验证。

团队成员仅有身份标识，权限与普通用户相同。只有首次在可信 SQL Editor 指定的管理员可以调用认证及管理操作。自定义 JWT claims、客户端开关及用户自行修改资料都不能授予管理员身份。

## 测试

安装 `playwright` 与 `@electric-sql/pglite` 后运行：

- `node scripts/test_forum_db.cjs`：真实 PostgreSQL 引擎执行迁移及 RLS，覆盖匿名/未验证限制、角色伪造、越权编辑、采纳、通知私有性、跨帖回复、团队权限、关闭、禁言、隐藏和删除后保留回复。
- `node scripts/test_forum_browser.cjs`：浏览器连接上述本地数据库；仅身份服务使用模拟账户，论坛读写都执行真实 SQL。覆盖发帖、HTML 转义、图片关联、回复公式、普通回答、采纳、站内消息、管理员认证、公开隐藏规则、历史页和手机截图。
- 既有 `test_accounts.cjs`、`test_favorites.cjs` 回归账户和收藏组卷。

可用 CHEMY_PGLITE_PATH 指定 PGlite 入口；浏览器测试使用本机 Edge。生产检查只读：确认唯一管理员、公共论坛可访问、匿名通知被拒绝，以及发布后的导航和页面。不自动注册或发送邮件，也不向生产论坛写入测试内容。
