# 1.7.2 图标更新记录

日期：2026-10-10（Asia/Shanghai）。本版仅更新应用图标，维护者明确要求简化测试并作为 1.7.2 发布。

维护者确认 SVG 为个人原创。保留蓝色下载篮与下载箭头，增加浅蓝白色圆角底板；统一 SVG、八档 PNG 和七档 ICO。覆盖 Windows GUI/CLI 独立 EXE、安装器、快捷方式、卸载列表、GUI 运行窗口，以及 Linux 应用菜单和桌面关联。Python GUI 使用包内 PNG；命令行在现有终端中运行时，终端自身的图标由终端宿主控制。

指南 B-01 至 B-07 从本版顺延至后续功能版，不宣称已经实现。

最终源码以 v1.7.2 标签为准，产物哈希以发行页的 `release-manifest.json` 与 `SHA256SUMS.txt` 为准。发布渠道的最终状态以 GitHub/PyPI 公开页面及仓库后续补记为准。

本轮仅验证图标渲染与小尺寸、Qt 资源加载、构建/打包配置、必要版本身份与归档检查，以及最终程序的离线启动。未重复下载、账号、四 Linux 桌面、IME/DPI、性能、安装异常等矩阵；1.7.1 记录仅作为历史基线，不视为这些项目在 1.7.2 重新通过。

本地证据保存在忽略目录 `build/release-1.7.2/`：

| 定向检查 | 实际结果 |
| --- | --- |
| 构建身份与 Debian 打包相关检查 | 18 项通过，`focused-tests.xml` |
| Ruff / 格式 | 通过，70 个 Python 文件格式一致 |
| SVG 派生资源 | 八档 PNG、七档 ICO 尺寸与透明角正确，ICO 中的各档 PNG 与独立文件逐字节一致 |
| Qt 应用图标 | PNG 加载、主窗口继承图标、`djhx-bilix-gui` 桌面身份通过；16～64 像素在深浅背景人工核对 |
| Windows GUI 绿色版与 standalone | 两种最终构建离线自检退出 0，包含图标加载；standalone 八档 PNG 与源素材一致 |
| Windows CLI | 最终 onefile 构建通过原有 11 项入口/帮助/版本/doctor/补全冒烟，编译报告确认未引入 Qt |
| Windows EXE 与安装器图标 | CLI、GUI onefile、standalone、Setup 四个实际 EXE 的内嵌图标解码后与素材一致 |
| Linux standalone | Ubuntu 22.04 / Python 3.14.8 实际编译及中文空格路径离线自检退出 0，`linux-standalone-smoke.txt` |

构建仍使用 Python 3.14.8、Nuitka 4.2.2、PySide6/Qt 6.11.2；依赖锁文件未改变。FFmpeg 保持原有官方 7.1.5 Windows 构建，Linux 使用发行版 FFmpeg。工作树凭据扫描 0 项；历史扫描仍是既有 22 项旧凭据发现，维护者已于 2026-10-03 确认历史凭据失效，本版没有新增发现或改写历史。

发行归档与公开渠道核验在最终上传时独立记录。未运行 Windows 安装/卸载/升级和四 Linux 桌面矩阵，不将编译、图标资源检查或离线自检作为这些项目的通过结果。

## 最终组装与公开发布

2026-10-10 已正式发布。源码提交 `8dbd009b9a064c33869bd87cfdb88c8183db2843`，`v1.7.2` 标签与代码已同步 GitHub、Gitea；标签及公开文件保持不变。以下为发布后补记，发行源码中的记录保留打包时快照。

- Python 3.11.2 隔离环境实际安装最终 wheel，CLI 版本、GUI 离线启动、安装元数据通过；十个 SVG/PNG/ICO 素材与工作树逐字节一致，见 `wheel-smoke.json`。
- 完整八项发行产物经过归档路径、许可材料、源码/元数据版本、大小与 SHA256 检查，见 `assemble.log`。最终 deb 的系统 SVG、八档系统 PNG、八档运行时 PNG 共十七项与源素材一致，桌面入口匹配，见 `archive-icons.json`。
- [GitHub v1.7.2](https://github.com/Koril33/bilix/releases/tag/v1.7.2) 为最新正式发行；十个公开文件的 API 大小及 SHA256 与本地一致，完整回下载清单和校验文件通过，见 `public-verification.json`。本次没有完整回下载 GitHub 所有大型二进制。
- [PyPI 1.7.2](https://pypi.org/project/djhx-bilix/1.7.2/) 的 wheel、sdist 已公开，元数据与两项完整回下载的 SHA256 均通过，见 `pypi-verification.json`；与已实际安装验证的 wheel 为同一文件。
- 网站源码通过 GitHub 最新正式发行接口显示版本，本版没有修改或部署网站；Gitea 同步代码及标签，不另建二进制发行页。

最终文件及校验清单保存于 `dist/release-1.7.2/`，Linux 构建 VM 已正常关闭。
