# AI 知识点组卷

用户输入知识点后，默认选择 5 道完整大题。任意小问直接涉及该知识点即可入选；主要考查优先，同等关联随机。来源筛选始终生效，题量不足不凑题。未知知识点提示更换表述，歧义或近似名称须用户选择候选，不静默改写。

组卷窗口提供常用知识点快捷按钮，以及可搜索规范名、同义词的完整知识点清单。清单只列实际有合格关联题目的知识点，每项显示当前来源筛选范围内去重后的大题数，点击即可按现有题量和高级设置组卷。题数使用与正式选题相同的置信度、关联完整性和来源规则，不把同一题的多个关联重复计数。索引更新后清单自动更新。

题目正文与答案正文复用 `presentation.json`，网页保留原专题编号，练习序号用于本卷定位。关联说明仅在答案内展示，指出原卷小问及其对应的专题编号。用户可删除、换题和重新组卷。

## 无需额外 Key 的索引工作流

由 Codex 直接阅读本地原题、答案及全部原图，逐题记录细知识点、小问、关联强度、置信度、理由及可追溯原文/原图证据。不把简单关键词命中当作语义分析。原始题库与图片保持原样。

使用已安装 Pillow 的 Python 运行：

```powershell
python scripts/knowledge_review.py prepare --group organic --topics 有机化学 --limit 5
```

输出 `output/knowledge-review/organic/packet.json`，包含完整题答文字、图片路径、用于目视阅读的联系图和源内容指纹。逐题实际阅读所有图片后，写入审读 JSON 数组，每条记录包含：

```json
{
  "id": "原题ID",
  "sourceHash": "packet中对应的指纹",
  "links": [{
    "concept": "知识点规范名",
    "aliases": [],
    "subquestions": ["8-1"],
    "strength": 2,
    "confidence": 0.95,
    "reason": "该小问涉及什么、为什么与知识点相关。",
    "evidence": [{"kind": "body", "quote": "原题中连续出现的文字"}]
  }]
}
```

`subquestions` 使用原卷编号，图片或正文内整体不可细分时可用“整题”。`strength`：3 主要考查，2 小问直接涉及，1 间接但作答必需。图片证据写为 `{"kind":"image","path":"assets/本题原图.webp"}`。每条证据必须属于本题；置信度不足 0.8 的关联不参与组卷。标签记录真实读题判断，不能以批量关键词规则代替。

```powershell
python scripts/knowledge_review.py import output/knowledge-review/organic/review-01.json
python scripts/knowledge_review.py status
python scripts/knowledge_review.py publish
```

导入时检查题目指纹、小问编号格式、置信度、原文摘录和原图归属。逐题原子保存到 `data/knowledge-analysis/`，支持中断后续做；已保存记录默认不覆盖。多个审读者按不重叠专题分工，主进程统一发布 `dist/knowledge-index.json`。源文字或图片改变会使旧记录失效；仅更新改变或新增的题目。索引严格记录实际覆盖数和是否完成全部题目。

`scripts/analyze_knowledge.py` 另外保留可选 Gemini 批处理接口，供维护者自行选择；网站运行及 Codex 直接审读均不依赖该接口。

## PDF 与打印

题目使用原有 `export-index/{topic}.json`；答案使用新增 `{topic}-answers.json`。后者由 `build_export_index.py --answers` 从已审核的答案册布局生成，覆盖全部 1933 题。更换原册后需重建索引，浏览器校验 `bookVersion` 后才导出。

Worker 继续裁剪和连续拼接原 PDF 矢量内容，保留字体、图形、来源与单页水印。答案中的额外关联说明单独排版，不改原参考答案。题目 PDF 不包含关联说明；下载过程使用选题快照，失败可重试，关闭窗口取消生成。仅新增卷名与说明使用本机中文字体栅格化绘制，原题与答案仍保留矢量内容。

网页打印先构造独立题目或答案视图，等待题图及字体加载完成，不把当前网站目录或隐藏答案一起打印。下载文件和打印内容均反映最终删改后的本卷选题。

## 检查

- `node scripts/test_ai_paper.cjs`：同义词、歧义、未知词、筛选、排序、不重复、缺题、真实 PDF、答案隔离、调整选题、打印、手机布局、失败重试。
- `python scripts/test_knowledge_analysis.py`：证据归属、源内容变更、无效引用拒绝、完整图像传入、截断拒绝、全部答案裁剪索引覆盖。
- 原有 `test_question_export.cjs` 等保留，验证旧选题下载没有被答案导出扩展破坏。

浏览器测试默认使用本机 8766 端口；可用 `CHEMY_TEST_URL` 指定预览地址。Node 依赖 Playwright，PDF 检查使用项目现有 Python 依赖。

## DeepSeek Agent

实时 API 组卷实现与公开网站部署见 [DeepSeek 接入说明](deepseek-deployment.md)。服务端运行 server/agent.mjs，使用仓库根 .env.example；网页配置仅含公开后端地址。
