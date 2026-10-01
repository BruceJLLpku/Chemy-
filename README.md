# Chemy 化学竞赛专题题库样例

公开网站：https://brucejllpku.github.io/Chemy-/

GitHub 仓库：https://github.com/BruceJLLpku/Chemy-

`main` 分支更新后，GitHub Actions 自动发布 `dist` 目录到 GitHub Pages。网页、题目数据、原图、专题 PDF、整理脚本均在同一仓库保存；临时预览文件与登录凭据不上传。

九个专题：有机化学、高分子化学、晶体化学、结构推断、元素化学、热力学与化学平衡、电化学、动力学、分析化学。

当前内容为第 39 届模拟卷 1 的两道完整大题：第 6 题“磷酸铁锂的 E-pH 图与回收”，第 8 题“二环化合物合成”。保留原题、原答案及评分细则出处。

网页正文与表格为 HTML；图形从原 PDF 提取，未使用 AI 生成或人工重绘化学结构。电化学图从原 PDF 的显示内容提取，保留原题对纵轴的处理；有机图保留原矢量路径及原图标签。页面背景装饰不属于题目图形，不随图导入。原文件未修改。

## 本地预览

用 Python 的 HTTP server 服务 `dist` 目录，打开显示的 localhost 地址。直接打开 HTML 文件不能读取题目 JSON。

## 内容维护

- `dist/questions.json`：题目、答案及来源，是网站与 PDF 共用的数据。
- `scripts/write_questions.py`：两道样例的内容源。
- `scripts/extract_figures.py`：原图图形提取。
- `scripts/make_pdfs.py`：从原 PDF 保留字体及图形，生成专题题目册与答案册。
- `dist/downloads`：可下载的专题 PDF，当前每册只含一道样例。

第一套卷批量导入工具：`scripts/paper1_manifest.py` 保存 10 道大题的主专题、原卷页码、原图和答案区域；`scripts/import_paper1.py` 提取网页文字和原图。该批内容正在核对，当前正式网站仍展示上面两道已确认的题目。原始 PDF 保留在本地，可放入 `sources/` 或通过 `CHEMY_SOURCE_DIR` 指定目录；安装 `requirements.txt` 并确保 `pdftoppm` 在 PATH 后可运行导入工具。临时渲染与核对缓存留在被忽略的 `tmp/`。

原参考答案第 6 题最后一问写成了 6-5，而题目册写成 6-4；网页展示时按题目册对应，并保留说明。原标准电势代入式遗漏的负号已补回，数值保持原答案 −0.679 V；PDF 保留原式并附说明。

题目与答案版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流使用，请勿用于任何形式的商业用途。本项目为题库展示样例。
