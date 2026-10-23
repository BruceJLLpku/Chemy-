# 贡献与维护指南

本仓库提交了可直接运行的 `dist/`、来源材料、整理脚本、历史检查记录及 GitHub Pages 工作流。预览网站和修复界面不需要重录 1933 道题。先阅读[权利与许可状态](rights.md)，本指南不扩大任何材料的许可范围。

## 在本地开始

在仓库根目录按 [README 的本地预览命令](../README.md#本地预览)启动 HTTP 服务，浏览器访问 `http://127.0.0.1:8765/`。Windows、macOS、Linux 都可预览已有静态文件。不要通过 `file:` 打开 HTML 测试 Worker 导出。

从干净 ZIP 或 Git 副本测试按题导出或完整专题册下载前，需要一次生成分题 PDF 和干净专题册（Python 3.11+）：

```sh
python -m pip install -r scripts/export-requirements.txt
python -X utf8 scripts/build_export_parts.py
python -X utf8 scripts/check_release.py --pdfs --parts
```

该流程直接读取已提交的 18 份专题册和导出索引，在 `dist/export-parts/` 生成每题的题目/答案文件、完整专题册 `*-book.pdf`、小型页框文件、各册清单与总 `manifest.json`。每道题文件按安全边界分成一个或多个小页，清除范围外的隐藏内容并压缩嵌入字体。浏览器只请求选中的题文件，复制其中绘制内容完成 A4 排版，不再反复嵌入完整专题页。

`dist/export-parts/` 是忽略的可再生目录，不提交数千份重复二进制文件。首次生成需要处理全库，重复运行复用有效缓存；源册、索引、版本或生成规则变化后再次运行。原卷扫描缓存、Windows 系统字体和 Poppler 不是这一步的依赖。生成器或校验失败时先解决具体错误，不要把未生成的目录当成可发布的网站导出功能。

完整生成后，可运行 `python -X utf8 scripts/test_clean_book_pixels.py --jobs 2`，逐页检查 18 册最终下载的书签、可提取文字及 144 dpi 图像是否与已经验证的清理页一致。此检查需要保留本次 `tmp/export-parts/` 页面缓存，只在比较时去除已知水印；结果保存在 `work/whole-book-validation/`。

完整题块验收运行 `python -X utf8 scripts/test_export_parts.py --all-renders`，默认按册使用最多 4 个独立进程；可用 `--jobs 1` 降低内存占用，默认抽样检查仍为串行。验收分为两层：生成清理页时，清理器已逐页证明原始内容与清理结果一致；题块测试再核对当前源册、索引、生成代码签名及清理页摘要，以该清理页为参考，在同一像素网格严格检查每个题块的 144 dpi 图像（最大通道差仍为 8/255）与 Unicode 字符出现次数，并检查零 Form 结构及嵌入字体统计。清理阶段已证明的旧编号边缘或采样差异不会作为题块容差再次放行。缺失或过期的清理页会明确报错，不会回退到原始册页；需保留本次页面缓存，每个进程最多同时打开 4 个清理页。`test_export_parts_validation.py` 验证篡改摘要、缺失参考、过期签名及真实缺线/缺字会被拒绝，并验证串行与并行报告一致、子进程失败会导致整体验收失败。

生成器默认同时处理两册，可用 `--jobs 1` 降低内存占用。构建中途失败后，已写入且摘要有效的页面缓存和分题文件可在下次运行复用；修改生成代码会使相关缓存失效。不要同时启动两个写入同一 `dist/export-parts/` 的构建。

复用 PDF 字节时，生成器仍从当前索引重建页块、位置、路径与字节数记录；损坏的清单条目按缓存未命中处理，未知题目条目不会保留。`test_export_cache_recovery.py` 用真实小型 PDF 检查这些恢复行为与错误页码缓存的重建，PR 工作流会运行该测试。

开发时可用 `--topics polymer analysis` 限定专题，或 `--ids chemy39-5-4` 限定题目；`--jobs 1` 单进程运行，`--force` 强制重建。这些只适合局部验证，完整发布仍需不加筛选参数运行，随后通过 `check_release.py --pdfs --parts`。该检查要求 18 册全部完成，检查源册/索引/生成代码摘要、题目覆盖、文件路径/字节数/SHA-256以及页块与源索引一致，并要求每册 `cleanBook` 文件与源册页数元数据一致；仅使用标准库，不解析 PDF 实际页数或绘图语义。PDF 结构及渲染应另用构建后的 `test_export_parts.py` 检查，其依赖已包含在 `scripts/export-requirements.txt` 中。其 `--allow-incomplete` 只适用于开发抽样，不构成全库通过。

PyMuPDF 构建依赖的 AGPL/商业双许可见 [rights.md](rights.md)。预览已部署的网站不需要安装这些构建依赖。

使用 Git 源码副本建立工作分支。GitHub 的 Download ZIP 不包含 `.git` 和提交历史；提交 PR 需要保留上游提交关系的 Git 仓库，不能把一次全新的 `git init` 提交当成上游基线。不要提交密钥、缓存、个人文件或本地检查产物。

纯静态数据检查只需 Python 3.11+，无需安装第三方库：

```sh
python -X utf8 scripts/check_release.py --pdfs --report output/release-check.json
python -X utf8 -m unittest discover -s scripts -p test_release_check.py
```

macOS / Linux 可把 `python` 换成 `python3`。检查失败返回非零退出码；不传 `--report` 时只向终端输出。`--pdfs` 会读取全部 18 份专题 PDF 并比对布局记录的 SHA-256，不访问网络。去掉该参数仍检查 JSON、图片引用、PDF 文件头和索引的题目、版本、顺序、页码与区间。检查不判断图片是否缺谱、公式是否正确，也不宣称验证了 Acrobat 编辑效果。

## 哪些文件是输入，哪些必须一起更新

| 内容 | 维护关系 |
| --- | --- |
| `sources/`、`sources/manifest.json`、`data/editions.json` | 原始来源身份与映射；保留原始字节，补正工作源单独存放 |
| `data/import_plan*.json`、`data/source_exceptions.json` | 单一主专题、边界和来源例外；修改时附原页证据 |
| `dist/questions.json` | 完整题干、答案与原始来源；从录入流程生成，不能仅改展示副本而遗漏此数据 |
| `dist/numbering.json` | 专题稳定编号与 PDF 版本；筛选不会重新编号 |
| `dist/presentation.json`、`dist/assets/` | 网页展示和重新编号后的图片；引用必须同步 |
| `dist/downloads/`、`data/print_index.json` | 18 份专题题答册与最终页码 |
| `data/continuous-books/`、`dist/export-index/` | 每册实际布局、字节摘要、逐题区间及安全换页边界；题册变化后同步生成题目和答案索引 |
| `dist/export-parts/`（不提交） | 从上述已提交题册/索引生成的干净矢量题块与完整专题册；`manifest.json` 记录生成版本、输入摘要与分题文件信息。变更题册/索引后运行 `build_export_parts.py` 同步 |
| `dist/knowledge-index.json` | AI 组卷的预先分析结果；题目实质内容变化后检查受影响条目，流程见 [ai-paper.md](ai-paper.md) |
| `tmp/`、`output/` | 可重建缓存和本地验证产物，均不发布 |

本仓库的网站入口是 `dist/index.html`，当前不维护单文件 `Chemy-offline.html` 的打包器。不要把另行下载的离线发行变体当成第二份权威源码手工复制维护。

## 按修改范围选择流程

### 界面与文档

直接修改 `dist/` 内对应 HTML、JS、CSS 或文档，运行轻量检查，并验证所改交互。至少覆盖桌面和 390px 手机宽度；涉及加载流程时模拟请求失败、恢复及重试；涉及下载时验证题目/答案、取消、失败恢复和生成期间重复操作。

现有浏览器回归脚本包括 `test_question_export.cjs`、`test_question_picker.cjs`、`test_topic_downloads.cjs`、`test_ai_paper.cjs`。这些脚本使用 Playwright，部分仍配置 `msedge` 通道；先安装对应浏览器或按测试入口支持的参数设置环境，再运行，不要把环境缺失当成通过。使用外部服务的脚本默认地址为 `http://127.0.0.1:8765/`，支持 `CHEMY_TEST_URL` 的脚本可指向其他本地端口。`test_export_parts_browser.cjs` 和 `test_topic_downloads.cjs` 默认启动独立的本地服务，并支持 `CHEMY_TEST_CHROMIUM` 指定 Chromium 可执行文件。整册测试默认检查热力学与化学平衡题答册；加 `--all-topics` 检查全部 18 册，设置 `CHEMY_TEST_SITE_DIR=output/site` 可检查整理后的发布目录。浏览器下载成功后仍需渲染检查，不能只判断 `%PDF-` 文件头。

### 题干、答案与图像修复

1. 用题目 ID 回查届次、套号、原题号和源页，确认题干与答案各自的材料；缺失题图不能未经核对直接拿答案图替代。
2. 修改相应提取规则或有来源记录的修复脚本，再更新原题数据、展示数据、图片引用及受影响的题答册。图形保持原卷内容；新图片使用内容摘要命名，避免浏览器复用旧图。
3. 同步受影响的打印索引、连续布局记录和两种导出索引，用 `python -X utf8 scripts/pdf_version.py` 同步 PDF 内容版本，再运行 `build_export_parts.py`。版本同步脚本仅需 Python 标准库，可跨平台运行，不加载旧排版器及其系统字体；它不重算页码/坐标。只更新 `bookVersion` 而保留旧页码/裁剪坐标或旧分题文件不能解决产物漂移。
4. 运行 `check_release.py --pdfs`，并在网页、完整专题册、单题题目/答案下载中查看同一题；渲染对照原卷的所有受影响页面，确认没有切掉谱线、坐标、结构式或评分内容。
5. 保存题目 ID、源页与裁切范围、生成命令和验证范围。历史 `data/*audit*.json` 只代表生成时的版本，不应在未运行相应检查时改成通过。

已登记的高分子第 1 题修正见 `data/question_figure_corrections.json`（题目 ID `chemy39-5-4`）。原题目 PDF 本身缺谱，修复采用官方答案册中重复题干的最终渲染图，不增加解答。`question_figure_corrections.py` 提供定向迁移，录入及编号流程也有相同修正入口；四项回归由 `python -X utf8 scripts/test_question_figure_corrections.py` 运行。重复处理时保留来源摘要与遮盖结果，不直接提取底层 JPEG；完整来源与页码见 [final-review.md](final-review.md#高分子第-1-题谱图修正)。

### 传统全库录入与重建

现有工具链已包含扫描、录入、编号、合并、连续排版、水印及索引生成；完整重建目前仍有以下前提，干净 ZIP 并不包含所有缓存：

- `requirements.txt` 和 `scripts/pdf-engine-requirements.txt` 列出基础依赖；导出索引另需 `numpy`、`pypdfium2`，渲染流程还使用 PATH 中的 Poppler `pdftoppm`。
- `pdf_typography.py`、`renumber_library.py`、`build_numbered_pdfs.py` 使用 `C:/Windows/Fonts/` 中的宋体、Times New Roman 等字体。完整旧排版链当前以 Windows 环境为前提，不等于本地预览也要求 Windows；不要把这些字体复制提交到仓库。
- 多个工具依赖未提交的 `tmp/library*/` 源页、图片、边界、编号和分册缓存；`rebuild_numbering.py --editions ...` 最终仍合并所有届次的展示与打印缓存，并非可以在空缓存中只重建一届。
- `audit_library.py` 还读取历史样例基线；`audit_numbering.py` 还包含原作者机器的 Git 可执行文件路径与历史提交比较。完整原图像素/历史审计需要先准备这些依赖，不能将轻量检查替代它们并宣称同样覆盖。

在已准备好相应环境、来源和缓存的维护副本中，传统流程为：

1. 用 `CHEMY_EDITION` 指定届次（联赛为 `0`），运行 `scan_library.py`，再对明确需要重录的套卷运行 `import_library.py N`。分类与边界规则必须先复核；从第一套重新录入全库可能覆盖既有修订。
2. 运行 `python -X utf8 scripts/rebuild_numbering.py`，生成展示、分册和合并题册。仅重建部分届次须满足其他届次缓存已完整的前提。
3. 生成题目和答案两套索引：

   ```sh
   python -X utf8 scripts/build_export_index.py
   python -X utf8 scripts/build_export_index.py --answers
   python -X utf8 scripts/pdf_version.py
   python -X utf8 scripts/check_release.py --pdfs
   python -X utf8 scripts/build_export_parts.py
   python -X utf8 scripts/check_release.py --pdfs --parts
   ```

4. 在缓存和基线齐备时运行 `audit_library.py`、`audit_numbering.py`，再做受影响页面的视觉核验和浏览器实际下载。

`import_paper1.py` / `make_pdfs.py` 是旧首套样例流程，不能直接覆盖当前全库。`publish_library.py`、`process_batch.py`、`run_ingestion.py` 含提交/推送或发布行为，不是本地预览命令；贡献者应提交 PR，由维护者审阅并合并，避免运行这些工具意外发布。

## PR 中记录验证范围

说明具体题目或触发步骤、修复前后表现、修改的数据源和同步产物，并列出实际运行的命令及结果。PDF 改动应附受影响源页/导出页的视觉对照、单题文件大小及隐藏内容检查；Acrobat 中移动图片和修改文字需单独实测，未测就明确注明。许可证与内容授权由维护者确认，不能用技术测试结果代替。

`.github/workflows/release-check.yml` 在 PR 中运行发布检查、损坏快照回归、裁剪内容清理、嵌入字体子集、整册资源与书签、缺谱修正及发布目录回归，核对已提交题库和专题 PDF 摘要。PDF 测试安装 `scripts/export-requirements.txt` 中的固定依赖；Node 测试覆盖浏览器 worker 的图案资源变换，并由 Python 对合成样例作像素比较。来源测试读取仓库内原始 PDF，不需要完整生成分题文件。这些测试有各自的样例范围，不代表全部化学内容正确，也不代替全库构建、真实浏览器下载或 Acrobat 实测。

字体回归还覆盖仅含 Macintosh 字符映射的字体、Symbol 映射、故意删除映射后的拒绝与回退，以及通过实际 pdf-lib 复制保存后，在独立进程中重新渲染。字体优化的外观检查会在切换比较文档时清空渲染缓存，避免候选文件借用原件字体而错误通过；不能只用文本提取相同来判断字形正常。运行命令为 `python -X utf8 scripts/test_pdf_font_subset.py`，其中 pdf-lib 复制回归需要 Node.js，PR 工作流已配置。

清理器默认比较 144 dpi 全页渲染，最大通道差须不超过 8/255。超限时只接受有独立证据的以下情形，并记录原始差异及验证证据，不使用页号白名单：

- 旧编号残边：变化只能在已识别编号洞的一像素周界内，属于移除的旧编号字形，每页最多 128 个像素。原像素须符合该编号的不透明灰度或 RGB 墨色叠加白底；结果只能变浅至白底，或变浅至身份、位置和绘制状态均保持的同色新编号。不能借编号范围解释其他化学文字、图片或路径的丢失。
- 字形舍入：字体、Unicode、字形 ID 和绘制状态匹配，位置与边界变化不超过 0.001 pt，剩余差异全部位于匹配字形边界内。随后在 144 dpi 下分别平移 `(0.37, 0.23)` 和 `(0.73, 0.61)` 像素，两次比较均须通过 8/255 阈值。
- 图片采样：实际绘制的图片与透明蒙版身份、像素、变换、完整状态和裁剪几何必须一致；局部不得混入其他绘制，图片的次数与顺序也须保持。完成这些证明后，两次严格的整页偏移采样均须通过 8/255 阈值。不能仅凭颜色数据摘要认定图片身份。
- 矢量舍入：只匹配满足限制的不透明描边、填充及其组合，保留几何、颜色、绘制顺序和数量。验证读取实际绘制覆盖及完整状态，包括变换矩阵、线帽、连接、尖角限制和虚线；不能用简化线宽重建非等比变换后的描边。完成结构与局部交互证明后，才允许两次严格采样，或实际墨迹一像素邻域内的双向残差检查，阈值仍为 8/255。

一页可以同时包含编号残边与字形、路径舍入。每次采样都必须重新证明并扣除合法的编号像素，剩余差异继续接受完整检查。文字或图形的大外接框不能证明其中所有区域都有墨迹；需要实际字形或路径范围，隐藏内容也只能凭明确的裁剪外部或空裁剪证据排除。绘制回调与页面绘制记录必须逐项对应，未知或不支持的状态不能静默跳过。

如果不透明矢量已经通过完整结构、绘制状态和局部交互证明，但 MuPDF 的采样检查仍未通过，另用固定版本的 PDFium 在 144 和 288 dpi 独立比较。两种分辨率均重新证明旧编号像素，并要求剩余全页差异不超过 8/255；页面尺寸、裁剪和像素坐标映射也必须一致。这条路径不跳过前置结构证明，不能把任意内容变化解释为渲染器差异；依赖包含在 `scripts/export-requirements.txt` 中。

回归包含删除化学字符、细键、重叠对象、编号附近的小填充或图片，以及移动、改色和裁剪变化等拒绝案例。`test_pdf_paint_evidence.py` 还验证斜体字形超出排版宽度的墨迹，以及非等比变换、剪裁、尖角和虚线的真实覆盖；`test_pdf_label_ownership.py` 验证其他内容不能借编号证明通过。两者由 `test_pdf_clip_cleanup.py` 入口一起运行。

MuPDF 的所有原生保存均使用 `garbage=1`，对象去重交给 pypdf，压缩仍可启用。此约束同时适用于中间页、分题、整册和字体优化，避免原生对象重排破坏共享图片及透明蒙版引用。验证针对重新打开的实际输出字节进行，并在切换文档时清空渲染缓存。`test_pdf_image_resources.py` 用程序化图片、独立透明蒙版、共享别名和部分剪裁检查资源及完整渲染；`test_pdf_compact_objects.py` 检查安全去重。这些行为回归不声称是底层重排缺陷的最小复现。

整册每加入 32 页执行一次安全压缩并重新打开，降低重复字体、图片和蒙版在内存中的累积；每个检查点都处理已累计的全部页面，因此不同批次仍可共享同一资源。去重迭代到对象数量稳定，再清理未引用对象，避免仅合并蒙版而遗漏其父图片。全部页面组装完成后才统一添加水印、书签和字体优化。跨批回归同时检查共享引用、独立透明蒙版、文字、书签和 144/288 dpi 渲染，批量大小本身不改变页面内容。

`.github/workflows/pages.yml` 在发布前安装固定的导出构建依赖，检查已提交数据，并从全部 18 份专题册生成 `dist/export-parts/`。通过 `check_release.py --pdfs --parts` 后，再运行 `test_export_parts.py` 解析全部分题文件、检查 PDF 结构，并抽样渲染各册的第一道题；默认不逐块渲染全部题目，完整逐块检查需另加 `--all-renders`。随后执行 `python -X utf8 scripts/stage_site.py --clean-books`，在 `output/site` 只复制题库、展示数据、HTML/CSS/JS 和 SVG 引用的图片及其他运行文件；下载使用 `export-parts/*-book.pdf` 干净专题册，原 `dist/downloads/` 仅保留在源码副本作为构建输入。实际目录总大小必须不超过 1,000,000,000 字节，否则终止发布。构建产物和来源素材均不会被脚本删除。

Pages 使用 `actions/cache` 保存 `tmp/export-parts/` 与 `dist/export-parts/`，缓存键包含运行环境、生成代码、固定依赖、源 PDF、索引和水印图片。恢复旧缓存后仍会运行生成器；生成器按输入摘要决定复用或重建，完整清单与文件摘要校验通过后才整理发布目录。缓存命中不是通过验收的替代，也不能让未完成的局部生成成为正式发布。

整理目录可以先用 `stage_site.py --clean-books --plan` 只读查看数量和字节数。`--clean-books` 会独立复用完整发布检查，核对源文件、生成签名、预期题目及全部题答册清单；不完整或过期的生成结果不能进入整理目录。`export-parts/` 只复制清单引用的题块、页眉页脚及整册 PDF，加上各册清单和总清单；未引用的旧文件留在源码目录，不混入网站。正式整理使用新的临时目录，逐文件复制并校验 SHA-256；成功后才把旧 `output/site` 移为唯一备份，再启用新目录，失败不替换旧站点。清单写入 `output/site-stage-report.json`，Pages 只上传 `output/site`。本流程不重新录入原卷或重排整套专题册。PR 合并前由贡献者与维护者检查相关本地生成、渲染和下载验证记录。
