# 1.7.9 发行与验收记录

日期：2026-10-13（Asia/Shanghai）。状态：**已发布，列明范围的验收和各渠道公开回验完成**。发行标签 `v1.7.9` 冻结在 `1f77079342fd2ad7f0e26b0a1e7835862fbe7eab`，基线为 1.7.8。本版修复绿色版更新，整理文档并补齐发布工具；旧版采用一次手动迁移，未增加失败更新接管界面。以下发行结果在标签冻结后补入，已公开文件和标签不修改。

## 已执行

- Windows CPython 3.14.8 / PySide6 6.11.2 更新专项回归：`tests/updates` 与 `tests/gui/test_updates_gui.py`，**60 passed**。
- 新增 8 项真实 Windows 进程/系统调用用例：修复前 **5 failed、3 passed**，修复后 **8 passed**。包括退出码 0/259、保留已退出进程句柄及查询期间退出；未强杀其他程序。
- GUI 专项验证失败原因及重试入口不被就绪提示覆盖，成功交接在工作线程结束后真正关闭，即使启用了托盘。
- 等待阶段失败用例确认已接受交接后错误可见，旧 EXE 未改变，也不在退出状态不明时启动第二实例。
- 最终统一验证：完整 GUI profile **514 passed、0 failed、0 skip**；CLI profile **378 passed、0 failed、0 skip**。两轮均通过版本身份、Ruff、文档链接、帮助/doctor/纠错/四种补全；GUI 离线启动也通过。证据分别为 `gui-20261013T024556Z-7afc86ce`、`cli-20261013T024557Z-513357a1`，位于 `build/validation/1.7.9/`。
- 工作树 Gitleaks 检查 **0 findings**，最终本地文件链接及差异空白检查通过。标题锚点另复核；统一验证本身不验证 fragment 或远程链接。

## Windows 10 冻结事务

Windows 10 专业版 build 19045、原普通用户交互会话、原生 Qt `windows` 后端。Nuitka 4.2.2 / CPython 3.14.8 / PySide6 6.11.2，生产入口与测试入口分别原生编译、独立启动自检通过：

| 程序 | SHA256 |
| --- | --- |
| 未注入测试钩子的生产 1.7.9 portable | `34cbc8c89623b87f74ac00ffea08c5593770fa9020b3cf9775ebc17ce37c453f` |
| 独立冻结 GUI 测试入口 | `6010a1bb2d27f1f8e15a8605d0190e29e399b1a9299d8ed5d3f1377adde6447b` |

2026-10-13 02:40:53–02:41:29 UTC，验收记录 `portable-handoff-3bb811390dc547b9950920239b08d69e`。以下六组全部通过：

1. 已登录普通用户、非提权令牌及非 Session 0 的交互会话。
2. 中文/空格目录、改名 EXE 的真实 GUI 更新按钮；生产 `handoff()` 创建非空父/子两个 PID 记录，复制自身为外部协调器并收到 `accepted.json`。
3. 旧 onefile 父/子程序真正退出；启动器继续持有旧父进程句柄，覆盖本次确认的失败条件。
4. 原路径 EXE 换为生产候选哈希；`.previous.exe` 精确保留旧测试 EXE 哈希。
5. 未改写的生产新版入口收到 `--updated`，窗口显示后事件循环写入 `startup.json`；只有一个新版 onefile 实例（父/子两个进程），保持原普通用户与会话，事务返回成功。
6. 非默认配置、GUI 偏好哨兵、配置备份及下载/用户目录标记保留，源测试包未改变。结束后仅清理本轮自己的进程与计划任务。

该结果是**离线签名、同版本测试入口 → 生产 1.7.9** 的完整事务。测试入口仅替换更新包发现，并发出自身 Qt 按钮信号；协调器、进程等待、替换、重启和目标生产 GUI 均使用实际实现。未自动操作系统认证或安装向导；测试程序不进入发行文件。

这验证修复后的协调器及真实退出链路，不等同公开网络版本发现，也不证明 1.7.7 携带的旧协调器能自然升级成功。旧版仍按已选择的手动迁移处理。

## 文档与部署工具

已建立当前文档索引、零上下文交接和简化回归入口，分开历史设计/验收与当前操作；需求和流程问题使用两份独立登记。官网、安装文件、应用更新和 APT 日常部署统一为 `bilix@djhx.site`，不依赖管理员密码。

新增 APT 发布入口的 **42 项隔离测试通过**。使用既有 1.7.8 公开材料，真实 GPG 公钥指纹、`Release.gpg/InRelease` 双验签、索引/包/by-hash 验证通过；服务器只读 `--check` 核对 bilix 身份、权限及不可变哈希，37 个实体通过。Git GPG 目录置 PATH 首位时也自动选原生 Windows OpenSSH并通过；SCP 使用同一 SSH。两份逻辑 Contents 从签名 `.gz` 解压核验，不把正常原文 404 当故障。

APT 工具已在本轮真实发布中执行：bilix 上传并激活 50 个实体文件，保留旧 pool/by-hash；签名索引仍为分步切换，不宣称整体原子。公开仓库在四个目标系统的升级回验通过，WF-03 已闭环。

## 最终构建与平台验收

- 锁定 Windows CPython 3.14.8 最终 GUI **514 passed、0 skip**，CLI **378 passed、0 skip**，完整集合只读检查通过；最低 CPython 3.11.2 GUI 亦为 **514 passed、0 skip**。最终证据 `gui-20261013T064840Z-87ac8a42`、`cli-20261013T065146Z-ecfe4db6`、最低解释器 `gui-20261013T063216Z-4026d351`。
- Ubuntu 22.04 原生构建与自检通过，Linux **500 passed、14 skip**；跳过均对应已有 Windows 通过的专用用例。传输回归三次各 7 项通过；40 个应用 Python 输入与宿主逐文件相同，无多余或缺失模块。Linux 构建脚本已修正读取 Windows CRLF 版本号的问题。
- 最终 Windows 10 build 19045 包验收 **20 项通过**：绿色版两次启动、原始 1.7.8 Setup 升级、同版重装、卸载、许可和用户数据保留。记录 `20261013T070618Z-8c3cf460`，绑定最终安装器和配套源码包。
- 同一最终 deb（SHA256 `27e7899f62f7a436461add05cfc8c562447695534e034fd86cc2edc6abe42f65`）在 Ubuntu 22.04/24.04、Debian 12/13 的依赖安装、offscreen/Xvfb 启动、1.7.8 升级、重装、卸载及配置/下载/虚构凭据文件保留均通过。使用已准备的专用 VM，不宣称本轮重新创建干净 OS。
- 最终 wheel 的最低 Python 隔离安装、8 个 CLI 入口/帮助/doctor/纠错/补全检查和无 Qt/cryptography 检查通过；wheel/sdist 的 twine 检查通过。
- Windows GUI 配套源码 220 项、Linux 源码 208 项、sdist 227 项与发行标签逐文件比对通过；换行按文本规范核对。三种更新身份验签通过；当前工作树与 794 份公开材料文本扫描 **0 findings**，`v1.7.8..HEAD` 增量历史亦为 0。全历史仍为已确认失效的旧凭据 22 项、四个旧提交，沿用[1.7.8 的维护者确认](validation-1.7.8.md#发行材料安全与渠道)，未屏蔽或重写历史。
- 本轮未重复在线账号/真实媒体或系统 DPI、高对比度、Wayland 中文 IME 实机矩阵。下载核心、主题和布局未改变，已有范围与未测限制沿用 1.7.8；本轮实际包和更新结果单独记录。

## 发布与公开回验

GitHub、PyPI、官网镜像、更新元数据、APT 和官网首页均已上线。GitHub/Gitea 源码与标签相同；Gitea 仍只镜像源码，不宣称提供发行附件。

- 官网镜像 15 个文件已完整回下载，大小/SHA256 与本地一致，三类更新身份验签通过；活跃渠道为 1.7.9、序号 **4**，不存在的元数据返回 404。
- PyPI wheel/sdist 已公开回下载且哈希一致，公开元数据为 1.7.9、Python ≥3.11；上传后的首次读取超时，随后独立回验通过，没有重复覆盖公开文件。
- 生产更新客户端在隔离进程中模拟旧版本 1.7.8，真实公网检查、下载和缓存重新校验通过；以当前 1.7.9 身份检查不提供更新。此项没有调用安装，不代替前面的冻结事务。
- 官网两轮各 25 个确定性浏览器场景通过；HTTPS 页面与本地字节/SHA256 相同，六条同版备用链接均返回 200。SHA256 `9d23fe5d684fa2f0241add4a79f57b24bbf5143f55d4941c3ba8e18f7a54a312`，部署与备份使用 bilix，无 sudo。
- GitHub latest 为 v1.7.9，15 个附件经实际公开 CDN 分段下载后大小和 SHA256 全部相同，三类更新身份验签通过。服务器侧整轮 HTTPS 回读超时，保留失败记录；最终成功证据为本机完整分段下载，不把上传摘要或超时当作完整读取通过。
- Ubuntu 22.04/24.04、Debian 12/13 分别核对公开 APT 公钥指纹、Signed-By/InRelease、候选 1.7.9-1，实际从原始 1.7.8-1 经公开源升级并启动自检通过；每轮从 HTTPS 取得同一 64,416,124 字节 deb。记录 `build/release-1.7.9/apt-<目标>/result.txt`，四轮均为 `public_apt=passed`。
- 主要公开证据：`github-verification.json`、`mirror-verification.json`、`pypi-verification.json`、`site-verification.json`、`live-client-verification.json`、`apt-publication.json`，均位于忽略的 `build/release-1.7.9/`。部署用户为 bilix，未使用 koril 的服务器密码或 sudo。

根因、迁移和官方方案来源见[绿色版修复说明](portable-update-fix.md)；开放流程项见[问题登记](workflow-issues.md)。原始 VM 和 APT 证据存忽略目录 `build/portable-update-fix-1.7.9/`，其中个人路径和私密材料不公开；新 clone 按公开测试入口重跑，不依赖这些本地文件。

## 最终八项产物

| 文件 | 字节 | SHA256 |
| --- | ---: | --- |
| BiliX-GUI-Portable-1.7.9-windows-x64.exe | 35855872 | 34cbc8c89623b87f74ac00ffea08c5593770fa9020b3cf9775ebc17ce37c453f |
| BiliX-GUI-Setup-1.7.9-windows-x64.exe | 47544191 | af6c264f48e175ed68759cdaf0fc76d6c1cbeb68b936327fce32ee8dedf71128 |
| BiliX-GUI-licenses-and-source-1.7.9-windows-x64.zip | 13828231 | a4ee3d55ed3c745d34660dc837bf678a03e65bc445b09030e3cd7b8fb8a5c96d |
| bilix-1.7.9-windows-x64.zip | 30068080 | ec97dc2d6955d675938b3f9ba591b18e3ac39d5fc378f36681ee37311672be8f |
| djhx-bilix-gui_1.7.9-1_amd64.deb | 64416124 | 27e7899f62f7a436461add05cfc8c562447695534e034fd86cc2edc6abe42f65 |
| djhx-bilix-gui_1.7.9_source.tar.gz | 830502 | 11c1f1ec36a4b22f91b905a0de2bb3eb0f378cb21ff190cf605b1724b49625de |
| djhx_bilix-1.7.9-py3-none-any.whl | 1914990 | fc15f5978453fe29e8ffd86178e58df3da56d671eb28e280b5f460df68682cdc |
| djhx_bilix-1.7.9.tar.gz | 13824701 | ec7ac2fc8c04da849c305bac303971ca565aa094f82ea3398b4b4e8d8b118fa8 |
