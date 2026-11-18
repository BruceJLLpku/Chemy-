# 权利与许可状态

本页记录仓库中可核对的声明、来源和待办，不授予新的许可，也不代表已经取得原命题组授权。

## 按材料区分

| 材料 | 当前可核对的信息 | 尚需维护者明确 |
| --- | --- | --- |
| 项目自身的网页代码、脚本与服务端代码 | 根目录尚无覆盖这些代码的许可证 | 代码权利人、拟采用许可证、适用目录及例外 |
| 试题、参考答案、评分细则、原图及其 PDF | 现有页面与 README 声明版权归 Chemy 化学奥林匹克团队原命题组，仅供学术交流、禁止商业用途 | 授权人、授权文件或公开声明、允许的使用/修改/再分发范围，以及是否允许公开打包全部材料 |
| 专题分类、编号、整理后的 HTML/JSON、裁图和专题册 | 来源映射见下表；这些材料包含原题内容，部分又有整理者的编辑贡献 | 整理贡献与原材料各自的授权范围，不能自动套用软件许可证 |
| Chemy 字标、水印与其他标识 | 仓库现有图案和来源说明 | 标识权利人及使用范围，是否有独立要求 |
| `dist/vendor/pdf-lib.min.js` | 同目录附有 [pdf-lib MIT 许可](../dist/vendor/pdf-lib-LICENSE.md) | 此许可仅覆盖相应第三方库，不能据此许可项目其余内容 |
| 分题 PDF 构建依赖 PyMuPDF / MuPDF | 官方提供 AGPL 与商业双许可；固定版本见 `scripts/export-requirements.txt` | 维护者需按实际使用、修改与分发方式确认适用许可及义务，不能从 pdf-lib 的 MIT 许可推导构建工具的许可 |
| PDF 中嵌入或构建时使用的字体 | 原卷嵌入字体；排版脚本另外使用系统字体 | 维护者需核对新增字体的嵌入/分发条件；本仓库不把系统字体许可转授给贡献者 |

GitHub 的[许可说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)区分公开仓库的查看/fork 与开放软件许可。当前只说明仓库缺少明确授权文件，不据此认定侵权，也不把“仅供学术交流”扩大解释为允许任意修改或再分发。

PyMuPDF / MuPDF 的许可证选项与全文入口见[官方许可说明](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)。该依赖在本地或 CI 构建时运行，部署的浏览器不加载 PyMuPDF。此部署方式描述不构成对 AGPL 适用范围的豁免判断，也不替项目或题库材料选择许可证。

## 来源与变更记录

| 记录 | 用途 |
| --- | --- |
| [`sources/manifest.json`](../sources/manifest.json) | 现有来源文件名、字节数、摘要，区分原始来源和派生材料 |
| [`data/editions.json`](../data/editions.json) | 第39～32届及联赛的题目/答案来源映射；32届原始答案与补正工作源分别列出 |
| [`dist/questions.json`](../dist/questions.json) | 题目 ID、原届次/套号/题号、正文和答案；未填写届次的旧条目按第39届处理 |
| [`data/library_manifest.json`](../data/library_manifest.json) | 录入过程与来源追溯信息 |
| [`data/source_exceptions.json`](../data/source_exceptions.json) | 原图边界、浮图与其他来源例外 |
| [`data/print_index.json`](../data/print_index.json) | 专题册中的题号、原来源和页码 |

上述摘要能证明文件身份，不能证明其授权范围。新增来源、替换图形、修正答案时，应在提交中记录对应原卷页码、修改理由及授权来源；不要移除现有署名或版权标识。

## 发布前由维护者完成

- [ ] 确认自身代码的权利归属并添加明确许可证，写明适用路径和内容/字体/标识等例外。
- [ ] 对题目、答案、图片、原始 PDF 和整理数据分别记录授权依据及可公开再分发的范围。
- [ ] 将 README、网站声明、下载 PDF 和发行包的权利说明统一。
- [ ] 如果部分材料不能公开再分发，确定可以公开的代码及演示材料范围，再由维护者调整发行内容。

这些事项需要有权许可的人作出决定。贡献者提交技术修复或添加本页，不会使许可问题自动关闭。
