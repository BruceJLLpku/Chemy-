# Chemy 化学竞赛专题题库

公开网站：https://brucejllpku.github.io/Chemy-/

GitHub 仓库：https://github.com/BruceJLLpku/Chemy-

`main` 分支更新后，GitHub Actions 自动发布 `dist` 目录到 GitHub Pages。网页、题目数据、原图、专题 PDF、整理脚本均在同一仓库保存；临时预览文件与登录凭据不上传。

九个专题：有机化学、高分子化学、晶体化学、无机综合与结构推断、方程式与元素化学、热力学与化学平衡、电化学、动力学、分析化学。

当前完整收录第39届模拟试题1–2，共20道完整大题。每道大题只设置一个主专题。已有题目的专题提供累计题目册、答案册，保留原卷字体、结构式、评分和来源。图文与对应关系将在全套录入结束后统一复核。

网页正文与表格为 HTML；图形从原 PDF 提取，未使用 AI 生成或人工重绘化学结构。电化学图从原 PDF 的显示内容提取，保留原题对纵轴的处理；有机图保留原矢量路径及原图标签。页面背景装饰不属于题目图形，不随图导入。原文件未修改。

## 本地预览

用 Python 的 HTTP server 服务 `dist` 目录，打开显示的 localhost 地址。直接打开 HTML 文件不能读取题目 JSON。

## 内容维护

- `dist/questions.json`：网页题目、答案及来源；与打印册共用原卷边界和分类清单。
- `dist/interface.css`：目录、导航、专题标题和下载入口的界面样式；仅在屏幕上生效。
- `dist/styles.css`：保留已认可的题目、原图及答案阅读排版。更新界面时保持阅读样式和题目渲染模板不变。
- `scripts/write_questions.py`：保留已认可的第 6、8 题内容，直接运行时导入完整第一套卷。
- `scripts/extract_figures.py`：原图图形提取。
- `scripts/make_pdfs.py`：从原 PDF 保留字体及图形，生成专题题目册与答案册。
- `dist/downloads`：可下载的 12 份专题题目册和答案册。

第一套卷批量导入工具：`scripts/paper1_manifest.py` 保存 10 道大题的主专题、原卷页码、原图和答案区域；`scripts/import_paper1.py` 提取网页文字和原图。两个原始 PDF 完整保存在 `sources/`，与用户提供的原文件字节一致，SHA-256 记录在 `sources/manifest.json`。也可通过 `CHEMY_SOURCE_DIR` 指定其他源目录。安装 `requirements.txt` 并确保 `pdftoppm` 在 PATH 后，依次运行 `scripts/extract_figures.py`、`scripts/import_paper1.py`、`scripts/make_pdfs.py`；打印册页眉使用 Windows 宋体。临时渲染与核对缓存留在被忽略的 `tmp/`，供后续检查复用。

录入流程：确认整道大题及主专题 → 一次缓存原卷文本与页面 → 批量提取原图和原生文字 → 核对化学式上下标、反应箭头、立体化学、所有小问及评分 → 生成并逐页检查专题 PDF → 提交并发布。无需逐题重新 OCR、重新绘图或重新编写页面。跨页题干会连续显示，原卷题号和来源页码保持可追溯。

分类与批量录入细则见 [录入规范](docs/ingestion.md)。原生文本及页面缓存会核对原文件 SHA-256、处理范围与版本；原图裁切记录源文件、坐标与输出摘要，未变动的原图直接复用。

仅修改分类或标题时，编辑清单后运行 `python scripts/import_paper1.py --metadata-only`，保留现有全部题干、答案及图形。此次分类调整只需运行 `python scripts/make_pdfs.py --topics elements inference`，生成受影响的四份 PDF；其余专题打印册不重生成。专题名称与归属调整不会改变原卷题目标题。

原答案第 7 题 Na-O 高度计算的“解得”行将 h1 写成了 h2；网页与 PDF 保留原文并加注说明。该注记不改变原答案数值。

原参考答案第 6 题最后一问写成了 6-5，而题目册写成 6-4；网页展示时按题目册对应，并保留说明。原标准电势代入式遗漏的负号已补回，数值保持原答案 −0.679 V；PDF 保留原式并附说明。

题目与答案版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流使用，请勿用于任何形式的商业用途。
