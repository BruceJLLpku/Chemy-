# Chemy 化学竞赛专题题库

公开网站：https://brucejllpku.github.io/Chemy-/

GitHub 仓库：https://github.com/BruceJLLpku/Chemy-

`main` 分支更新后，GitHub Actions 自动发布 `dist` 目录到 GitHub Pages。网页、题目数据、原图、专题 PDF、整理脚本均在同一仓库保存；临时预览文件与登录凭据不上传。

九个专题：有机化学、高分子化学、晶体化学、无机综合与结构推断、方程式与元素化学、热力学与化学平衡、电化学、动力学、分析化学。

当前完整收录第39届22套、第38届24套、第37届3套、第36届25套、第35届26套模拟试题，共980道完整大题。每道大题只设置一个主专题。九个专题提供累计题目册、答案册，保留原卷字体、结构式、评分和来源。图文与对应关系将在全部录入结束后统一复核。

网页正文与表格为 HTML；图形从原 PDF 提取，未使用 AI 生成或人工重绘化学结构。电化学图从原 PDF 的显示内容提取，保留原题对纵轴的处理；有机图保留原矢量路径及原图标签。页面背景装饰不属于题目图形，不随图导入。原文件未修改。

## 本地预览

用 Python 的 HTTP server 服务 `dist` 目录，打开显示的 localhost 地址。直接打开 HTML 文件不能读取题目 JSON。

## 内容维护

- `dist/questions.json` 保存原卷题目、答案和来源，不覆盖原始题号。
- `dist/numbering.json` 是网站与 PDF 共用的专题编号表。每个专题从 1 开始；筛选试卷不会重编号。
- `dist/presentation.json` 保存展示内容：大题第 N 题，小问 N-1、N-2，多层小问 N-2-1。原题号只在来源中标注。
- `dist/downloads` 提供九个专题的题目册、答案册，共 18 份。卷首提示、常数及评分说明不展示；题干内必要提示和逐题评分保留。
- `scripts/rebuild_numbering.py` 批量更新编号、含题号的原图局部标签和 PDF。只复用或替换编号字形，化学结构、反应箭头与图表不重绘。缓存按编号计划复用。
- `scripts/audit_numbering.py` 核对网站和打印编号，检查原数据未变、编号区域之外原图像素一致，以及 713 题的题答打印索引。
- `data/print_index.json` 记录各题在累计打印册中的编号、来源和页码。

三届六份原始 PDF 完整保存在 `sources/`，原文件字节不改；归档的首套打印册保留在 `data/book_bases/`。原始完整图文复核见 `data/audit_report.json`；此次展示编号与打印册检查见 `data/numbering-audit.json`。

更新来源内容或分类后，先运行对应录入工具，再执行 `python scripts/rebuild_numbering.py`，最后执行 `python scripts/audit_numbering.py`。当前完整题库不能直接运行旧的首套专用脚本覆盖，旧脚本与归档保留供来源追溯。

原参考答案中已确认的编号笔误按原题对应：39 届第 1 套第 6 题答案的 6-5 对应原题 6-4；36 届第 25 套第 4 题答案单列的 9-4 对应该题第 4 小问。原电势代入式和 Na-O 高度的既有来源校注继续保留。试剂当量、反应编号、谱线编号与化学结构标号不作为小问题号替换。

题目与答案版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流使用，请勿用于任何形式的商业用途。

本地录入与打印册生成使用 pikepdf 原生引擎；重新搭建录入环境时安装 scripts/pdf-engine-requirements.txt 中的依赖。GitHub Pages 直接发布 dist 静态文件，访问网站和下载 PDF 无需安装依赖。
