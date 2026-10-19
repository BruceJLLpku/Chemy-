# AI 组卷接入 DeepSeek

已准备代码和部署配置，尚未部署到公网，也未使用真实密钥进行付费联调。用户访问的前端继续放在 GitHub Pages，独立的 Node 后端保存密钥并调用 DeepSeek。

## Agent 做什么

1. DeepSeek 读取用户自然语言需求和完整知识点目录，识别规范知识点。歧义或近似名称会请用户选择。
2. 后端按专题、届次、试卷，从经过审核的关联索引召回候选，再由 DeepSeek 选择完整大题及其关联小问。
3. 服务器和网页分别验证题号、重复、题量、来源范围及关联引用。展示、换题、原答案和 PDF 使用既有原题数据。

当前索引审核了 **95 / 1933** 道大题。DeepSeek 在这批关联证据中选题，不表示它已经重读全部题库或看过全部原图。关联说明直接引用审核记录，不能由模型自由编造。扩大覆盖范围是单独的后续标注工作，本轮不进行付费全库分析。

## 本地启动

需要 Node.js 22 或以上。无需 npm 安装。

复制仓库根的 `.env.example` 为 `.env`，只在 `.env` 填写 `DEEPSEEK_API_KEY`。密钥不要发到聊天，不要写进 `dist/`。在仓库根运行：

```powershell
node --env-file=.env server/agent.mjs
```

打开 `http://127.0.0.1:8788/`。本地服务自动将组卷模式设为 DeepSeek；`/health` 的 `configured: true` 只表示服务器读到了密钥，**不表示已鉴权成功**。点击组卷才会调用真实模型，一般一次组卷调用两次 API；明确点击候选知识点后只需选题调用。重新组卷会再次计费，删题及从已有候选中换题不会调用 API。

## 公开网站部署步骤

建议先在 Render 的 Free 实例试运行。免费实例 15 分钟无访问会休眠，重新启动约需一分钟；额度及计划以控制台为准。DeepSeek API 独立计费。稳定公开服务可在试运行之后再选择常驻实例，本轮不创建付费资源。

1. 注册并登录 [Render](https://dashboard.render.com/)，连接自己的 GitHub 账号。后端代码须先存在于将要部署的分支；当前本地改动尚未推送。
2. 选择 **New → Blueprint**，选择 `BruceJLLpku/Chemy-` 及包含本次代码的分支，让 Render 读取仓库根的 `render.yaml`。如果手动创建 Web Service，Root Directory 留空，Build Command 为 `node scripts/build_agent_bundle.mjs`，Start Command 为 `node output/agent-service/server/agent.mjs`。
3. 在 Render 环境变量中填写 `DEEPSEEK_API_KEY`；模板中的 `sync: false` 要求自行填写，不会提交密钥。确认 `DEEPSEEK_MODEL=deepseek-flash`、`HOST=0.0.0.0`、`SERVE_STATIC=false`、`NODE_ENV=production`、`ALLOWED_ORIGINS=https://brucejllpku.github.io`。端口采用 Render 自动提供的 `PORT`，不要填前端地址作为端口。
4. 部署成功后，从控制台复制实际 HTTPS 服务地址，打开该地址的 `/health`。应看到 `ok: true`、`configured: true` 和真实审核覆盖数。不得将示例域名当成真实部署地址。
5. 编辑前端 `dist/ai-config.json`：将 `mode` 改为 `deepseek`，`backendUrl` 填刚才的服务 Origin（HTTPS，不含 `/api/compose` 路径）。这里仅填写公开地址，**不放密钥**。后端就绪后才发布前端，避免用户进入尚不可用的组卷模式。
6. 在公开网页上测试一份短卷、歧义名称、来源筛选、换题、取消、错误重试和 PDF 下载。这才是线上真实联调；本轮的 mock 测试不能替代它。

仓库根就是 `chemy-site` 这个 Git 仓库，Render Root Directory **不是** `chemy-site/`。构建脚本输出最小后端运行目录，仅包含 Agent、选题引擎、知识点证据索引、题目元数据和编号版本，不复制图片、PDF、密钥或 Word 文件。Render 从现有仓库克隆时仍会获取该仓库的源码/历史；如果日后克隆耗时过长，可以再建立独立的小后端仓库。

`dist/ai-config.json` 默认保留 `mode: local`。这是明确显示的本地索引模式；启用 DeepSeek 后，模型或后端失败会显示错误，不会偷偷退回本地选题冒充模型成功。

## 公网调用额度

默认同一来源地址每分钟 6 次组卷请求，同时最多处理 2 个组卷任务，每个上游请求 45 秒超时，单次最多输出 4096 tokens。没有自动重试，避免失败重试扩大费用。全局每天最多 200 次上游调用（UTC 日，通常相当于最多 100 份自然语言组卷；识别失败、取消和上游报错也可能已计入/计费）。可通过模板列出的环境变量调整。

这些计数目前在**单个进程内存**中，重启、重新部署和 Free 实例休眠后都会重置；因此不构成跨重启的硬预算保证。正式扩大公开使用前，应改用持久化计数或平台 API 网关，并按实际账户能力设置消费额度。服务不信任任意客户端传入的 `X-Forwarded-For`；在 Render 代理后可能将多位访客计入同一地址，限流会比较保守。多实例部署需要共享限流存储。

CORS 仅允许指定网页 Origin，它不是用户认证；命令行客户端仍能伪造 Origin。公开访客不需要也不应该填写站点作者的 API Key。需要严格防滥用时应增加服务端验证的登录或验证码，而不是把可复制的“访问密码”写进公开 JavaScript。

## 检查命令

```powershell
node --test scripts/test_deepseek_agent.mjs
node scripts/test_deepseek_browser.cjs
node scripts/test_ai_paper.cjs
```

浏览器检查需要已有 Playwright 和 Edge；Python 题库验证使用原项目依赖。浏览器新增测试会模拟 DeepSeek 上游，避免消耗真实余额。生产后端不提供静态文件访问，密钥缺失、鉴权失败、余额不足、限流、超时、无效模型结果均有明确提示。

参考：[DeepSeek API](https://api-docs.deepseek.com/)、[Render Web Services](https://render.com/docs/web-services)、[环境变量与密钥](https://render.com/docs/configure-environment-variables)、[Free 实例限制](https://render.com/docs/free)。
