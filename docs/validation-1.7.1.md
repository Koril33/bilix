# 1.7.1 验收记录

更新：2026-10-09（Asia/Shanghai）。**1.7.1已于2026-10-09发布；五项收尾、最终材料、公开回下载与全新CLI/GUI安装均通过。** 本轮按五项收尾全部完成、最终候选测试通过后发布，未沿用1.7.0的范围例外。

交接入口：[恢复交接与下一步](handoff-1.7.1.md)。证据在忽略目录 `build/release-1.7.1/`、`build/validation/1.7.1/` 和 `dist/`。恢复后复用输入未变且明确通过的结果，只补缺口或变更影响的检查。下文简写日志及 `native/` 均相对于 `build/release-1.7.1/`。

## 范围与五项门槛

产品版本 1.7.1，工作起点 `12d1067499528d24eccf25e805c2e0ceea826abe`，最终源码以v1.7.1标签为准，产物以发行页release-manifest.json与SHA256SUMS.txt为准。指南 B-01 至 B-07 的全部能力、前置和验收均为 1.7.2 必须完成的内容，详见[完整指南 B](cli-gui-ux-review.md)及[路线图](roadmap.md)。网站只修改、验证并提交源码，维护者自行部署。

| ID | 必须完成的内容 | 当前状态 | 验收证据 |
| --- | --- | --- | --- |
| CLOSE-01 | 支持平台真实字体、目录选择器、键盘、中文 IME、100/150/200% DPI、小屏；完整 Wayland | 通过 | Windows三DPI/真实小屏、四Linux发行版最终安装与三DPI可见矩阵、完整DRM Wayland通过；详细范围如下 |
| CLOSE-02 | Windows 真实磁盘耗尽、正常用户取消，旧程序/注册表/用户数据保护 | 最终 Setup 通过 | 两项 result 均 passed，绑定当前 Setup 同一 SHA256；退出5/2，旧 runtime 全哈希、版本注册表、用户数据与残留清理通过 |
| CLOSE-03 | 完整冻结窗口首帧、旧新版空闲内存、真实下载峰值、千项滚动/进度交互 | Windows原生基线通过 | 最终Portable与公开1.7.0各4个有效客户区首帧、同条件RSS；同样本真实下载及FFmpeg同刻树峰值；真实按键/末行/进度/筛选/终态的受控合成千项对照通过。不另加可选Linux性能重复测试 |
| CLOSE-04 | 网站成功/失败/无 JS、宽窄屏、键盘验证及源码提交 | 页面验证通过，源码已提交 | 25项 Chrome 断言通过，48张截图；在线 API 另列观察。网站源码随版本提交，由维护者部署 |
| CLOSE-05 | 源码、导入位置、安装元数据、归档身份一致，不一致强制失败 | 实现及回归通过 | validate静态读取checkout；两个CLI及四个GUI build/package入口强制身份检查，wheel/sdist组装核对内部身份；真实旧wheel/旧元数据同号、其他来源及新旧混合负例拒绝。最终归档身份、源码对应、安全路径及公开文本秘密预审通过；公开完整哈希复核通过 |

## 本版修复

1. 初始窗口按可用屏幕限制尺寸与最小值；Wayland 首次显示前按实际屏幕限制高度，修复1024×768首次显示越界。
2. 任务表按可见区域估算列宽，避免千项队列逐次扫描全表。
3. 中文预编辑时隐藏 URL 占位提示，提交/取消后恢复；Tab与Shift+Tab可离开及返回多行输入框。
4. 版本检查核对当前源码、导入版本及位置、安装元数据；两个CLI与四个GUI构建/打包入口先检查再执行。validate直接静态读取checkout版本，同时核对导入版与安装元数据，允许同版实际wheel的不同导入位置；wheel/sdist文件名、内部源码、元数据不一致，旧新版混合或重复元数据均拒绝。
5. 网站改用GitHub发行接口、GitHub/Gitea入口与异常回退，补持久真实浏览器验证。
6. 增加专用VM的桌面、安装异常和性能工具。工具静态检查通过不等于对应实际验收完成。

## 自动检查

| 环境或检查 | 最新准确结果 | 证据 |
| --- | --- | --- |
| 隔离纯CLI Python3.11.2 / 3.12.12 / 3.13.5 | 各295通过，零失败/错误/跳过 | `cli-regression-summary.json` 的 `stable_final_matrix` |
| GUI Python3.11.2，实际安装已测候选wheel | 318通过，零失败/错误/跳过 | `cli-wayland-regression-summary.json`；`build/validation/1.7.1/gui-20261009T012327Z-3ea4d1db/result.json` |
| 锁定GUI Python3.11.2最终定向 | 23通过，零失败/错误/跳过 | `cli-gui-py311-wayland-final.xml` |
| 身份、Python/GUI归档及发布校验定向 | 49通过，零失败/错误/跳过，包含真正新旧来源混合负例 | `release-identity-final.xml` |
| 最后补齐CLI入口与checkout静态身份检查 | 26通过，零失败/错误/跳过；Ruff/格式通过，真实旧/新wheel正反例及无Qt CLI正例通过 | `version-entry-final.xml`、`version-entry-actual-wheel-1.7.0.json`、`version-entry-actual-wheel-1.7.1.json`、`version-entry-cli-noqt-positive.log` |
| Ubuntu22.04最终Linux构建环境 | 312通过、6项Windows专用跳过；传输独立重复3次各6通过；Ruff/格式通过 | `linux-build-candidate.log` |
| 真实Chrome网站 | 25项断言全部通过；在线API观察HTTP200、当时最新发行v1.7.0 | `web-validation-final-v3/result.json` |

自动校验同时覆盖版本、帮助、doctor、错误建议、PowerShell/Bash/Zsh/Fish补全及GUI启动冒烟。在318轮全量之前的变化仅为GUI app/test，CLI核心、测试、工具与锁文件未变，三组295结果据此复用，原因已写入汇总；其后版本工具补丁的定向补证另列。已测wheel内app、实际安装与工作区一致：app SHA256 `4ae65d3cd5c531d0bc53215b5305b5471d31c3c0e90c2b1306318f74b1ee40be`，已测wheel SHA256 `3bfce0c86bd9e33ba4d145b534306607a58d5227f6ec0cb633b9e84bca516e1f`。最终README元数据已刷新，发行wheel SHA256 `02a9c16a660162b4d36d3c366cc8fa6fcb450c9cc07cbe25bfc8918027f7a404`。`final-python-wheel-refresh.json`与`final-wheel311/archive-identity.json`证明26项产品文件与已测wheel相同（Python源码只允许CRLF/LF等价，二进制原字节一致），依赖/许可/版本头不变；新建Python3.11.2环境安装最终wheel后，26项实际文件与wheel逐字节相同，源码/导入/元数据1.7.1、Qt6.11.2、最终README长说明、CLI help/doctor和GUI冒烟全部通过，见`final-wheel311/final-wheel311.json`。最小安装验证工具最初错误地拒绝uv合法的空archive_info对象，已按对象类型、候选URL及实际文件验证修正；原失败日志保留，未重复安装或全量回归。

Linux6项跳过为Windows gui-scripts 1项、依赖Windows PowerShell与已安装blx launcher的CLI测试4项、Windows console control event 1项；Windows全量没有跳过。不得写成Linux零跳过。

真实版本负例：`cli-build-identity-stale-metadata.json` 为源码/导入1.7.1、安装元数据1.7.0而拒绝；`cli-build-identity-wrong-import.json` 为三者同版但导入另一来源而拒绝。不得用 `PYTHONPATH=src` 掩盖旧元数据。

恢复后只读审查另发现CLI build/package缺少强制入口、validate把导入版当源码版的问题，已补齐并用26项定向检查验证：真实公开1.7.0 wheel的导入版与元数据均1.7.0，而checkout为1.7.1时，validate及两个CLI入口均拒绝；当前1.7.1实际wheel可通过validate，但用于构建/打包时因非当前editable来源拒绝，两轮均未进入Nuitka或写包。纯CLI3.11的正例身份1.7.1通过，PySide6未安装且未导入Qt。此次只改版本工具与测试，不改产品、锁文件或二进制；上述295/318是已有全量结果，不能写成新增测试也已全量重跑。

## 真实桌面证据

Windows10 build19045真实已登录桌面使用Microsoft YaHei UI，中文字形索引非零；三种缩放各有真实IME候选截图、一次“中文”提交、Tab到“导入 URL 文件”、Shift+Tab回URL、小窗口键盘到“开始下载”记录和实际按键计数。此完整套件使用Tab修复wheel SHA256 `627d3f2aef320bd2feed56da7fc5562a528491ffec9813b453cbccea76de1e0a`；最终wheel `3bfce0c86bd9e33ba4d145b534306607a58d5227f6ec0cb633b9e84bca516e1f`只增加Wayland屏幕边距，Windows分支未变，因此复用三DPI结果。

| 已测Windows场景（Tab修复wheel完整套件） | Qt实测 | 证据 |
| --- | --- | --- |
| 100% | DPR1，逻辑桌面2560×1600 | `native/native-final100/result.json`及目录、IME、焦点截图 |
| 150% | DPR1.5，逻辑桌面1707×1067 | `native/native-final150/result.json`及目录、IME、焦点截图 |
| 200% | DPR2，逻辑桌面1280×800，可用1280×760，初始窗口940×712 | `native/native-final200/result.json`及目录、IME、焦点截图 |
| 100%小屏 | 真实1024×768，可用1024×728，初始940×680；键盘到开始动作、目录接受 | `native/native-small-desktop100/result.json`、`start-focus.png`、`picker-accepted.png` |

最终冻结Portable SHA256 `f4a518a985de81f9d530640f2d4e794d29059222de390e8408c44815fb82fb5e`另做100%真实功能补测（`native/frozen-final100-*.png`：首屏、IME候选/提交、目录、Tab）和150%原生补测（`native/frozen-final150-check-v2.json`及IME截图，实际Windows DPI144）。没有宣称最终冻结程序重新跑过200%完整套件。

Ubuntu22.04完整可见DRM Weston会话使用原生 `wayland` backend与真实socket，未用headless/offscreen代替。`native/bilix-native-171-wayland-v3/result.json` 为passed，1024×768初始窗口940×688；记录IBus真实预编辑13次、提交1次、“中文输入”、52个按键事件。Tab、目录及展开高级选项小窗到开始动作已有 `native/wayland-v3-*.png`、`visible-wayland-v3.log` 等证据。

Wayland v3已有合成1000行、Ctrl+End、进度与筛选记录，但不把它的宽松末行记录冒充加强断言。v4下方动作不达来自驱动仅发Tab停留于表格单元格，尚无加强通过结论；千项性能门槛以以下Windows严格对照闭环，不增加重复性能测试。最终Linux可见矩阵仍检查实际交互，已完成Wayland IME不重复。

| 最终Linux可见矩阵 | 实际结果与证据 |
| --- | --- |
| Ubuntu22.04 | 最终deb生命周期退出0，三DPI通过；`native/ubuntu2204-final-aggregate.json`复用完整96与补144/192，保留失败父记录 |
| Ubuntu24.04 | 最终deb生命周期、三DPI通过；`native/ubuntu2404-x11-final-20261009T125415Z-303ae418/result.json` |
| Debian12 | 生命周期退出0后只补桌面，三DPI通过；`native/debian12-x11-final-v2/result.json` |
| Debian13 | 最终deb生命周期、三DPI通过；`native/debian13-final-aggregate.json`复用通过的96并补144/192，原失败矩阵保留 |

总汇 `linux-final-all-platforms.json`通过。各OS的96/144/192真实Xft DPI对应Qt DPR1/1.5/2，均有NotoCJK非零中文字形、IBus预编辑/“中文输入”提交、Tab/Shift+Tab、实际中文空格子目录、小窗口高级选项/键盘动作、1000项真实Ctrl+Home/End与原生滚轮、末行完整可见/进度变化/筛选/终态严格断言。此详细套件运行最终生产界面的源码探针；另以每个平台实际安装的最终deb正常启动完整冻结窗口，`native/packaged-x11-<target>/result.json`均通过，实际ELF同SHA256 `23978e1a26b7911ae08477645f08f8f328cae28641c39b8af6b22e28de5e0ed0`，有物理桌面截图及正常Alt+F4关闭。

Ubuntu22复用构建VM；另外三OS复用专用测试VM并按需安装桌面，均不宣称全新干净环境。生命周期包含原始公开1.7.0、升级/重装、APT降级保护、卸载及用户文件保留。修复的测试工具问题包括IBus引擎已选中却返回1、表格Tab单元格导航、鼠标已到位时xdotool --sync等待，以及Qt/旧xdotool坐标口径；最终用xwininfo绝对客户区与EWMH工作区/边框比较物理坐标。Debian默认8MiB显存无法设置1920×1080，专用Vagrant配置明确128MiB，并补kbd工具；控制台配置用非交互执行。Ubuntu24下载慢时临时使用TUNA镜像，官方签名密钥不变，完成后恢复原软件源。Debian13基础镜像的旧DBus machine-id为空，已仅在专用VM同步有效系统ID并重启桌面，解决Qt与IBus发现路径不一致；依据[Qt官方X11 DPI优先级](https://doc.qt.io/qtforpython-6.11/overviews/qtdoc-highdpi.html#configuring-x11)，桌面Xsettings DPI优先级高于xrdb，驱动同步实际XFCE DPI并恢复原值，仍严格断言Qt DPR1/1.5/2。失败日志保留，未改写成通过。

最终deb还在1024×768完整DRM Wayland会话确认首屏，`native/frozen-wayland-final/frame-validation.json`为原生完整帧通过，实际进程加载已安装libqwayland/libQt6WaylandClient，DISPLAY未设；物理截图人工核对控件、中文与状态栏完整。观测工具等键盘关闭超时后按所有权终止进程，因此该补测只证明冻结程序原生首屏，不标正常关闭或性能通过；原有Wayland生产界面IME/键盘/目录用例仍以v3通过记录为准。会话已停止、VM已正常关机。

## Windows原生性能与清理

权威汇总 `native/performance-final.json` 为passed；环境为Windows10 19045、VirtualBox7.0.12、4vCPU/3GiB、VBoxSVGA128MiB，系统真实100%/DPI96，物理桌面2562×1318；测量时其他VM暂停、无编译负载。冻结样本每次新进程，不清OS缓存，不称冷启动或冷/热各五次。外部50ms轮询desktop DC并裁剪客户区的首次有效已绘制帧是观察上界；源码探针首帧不用于替代完整冻结启动。

共8个有效帧，旧/新版各4个，PNG均人工核对客户区实际控件已画出。原v2旧版repeat样本2仅DWM标题/边框，虽然当时工具报告passed，已明确排除；后来独立补测一个有效旧版样本替换，保留排除记录与先后顺序。空闲RSS在见帧后采15秒，去除前5秒后计算每样本中位数，再按样本等权汇总。

| Windows受控指标 | 公开1.7.0 | 最终1.7.1 |
| --- | --- | --- |
| 冻结客户区首帧中位数（范围） | 1.768秒（1.656–2.081） | 2.036秒（1.827–2.190） |
| 空闲进程树RSS中位数（各样本中位数范围） | 154.254MiB（151.371–159.281） | 150.215MiB（142.113–156.992） |
| 同样本真实下载观察峰值 | 131.457MiB | 130.402MiB |
| 同条件插入1000项动作耗时 | 0.114秒 | 0.082秒 |
| 同条件1000项终态动作耗时 | 21.544秒 | 0.448秒 |

真实下载使用同一公开视频 `BV1j4411W7F7`，两版均完成；独立psutil采样同时刻目标进程树RSS，包含FFmpeg/conhost，实际采样间隔中位约3.93/4.45ms，分别413/381个下载样本及32/31个FFmpeg样本。表中峰值是采到的下界，不把各进程不同时间峰值相加；该部分在相同Python GUI/wheel环境测量，不能称冻结EXE下载峰值。两输出同SHA256 `61624b63db0ff88662f459c9bfbc8c36654830cd00afa4c1629ddde49574bd75`，`native/download-full-decode-final.json`确认ffprobe退出0、HEVC640×360/AAC，FFmpeg全量解码退出0且无错误；字节相同所以一次完整解码覆盖两份输出。

千项对照在相同Python3.14.8/PySide6 6.11.2/psutil7.2.2、真实100%、1100×1000窗口测量，合成进度无网络；实际Ctrl+End/Home/End、末行999全可见、进度变化、筛选和终态均有快照。每版一组受控序列，耗时为探针动作执行，不是下载总时间。该小VM、样本与缓存条件只作本次基线，不宣传普遍启动、内存或下载峰值改善。

`native/windows-cleanup-final.json`为passed：本轮owned进程、临时计划任务、临时VHD、R盘卷均为0；Portable/Setup哈希再次核对，登录凭据未改变。Windows测试与清理已完成，不重复开启验收。

## 最终Windows安装异常

两项绑定当前 `dist/gui/BiliX-GUI-Setup-1.7.1-windows-x64.exe`，SHA256 `f2c816d2dabbb5f29ab8bc6bb2af5e57c6f59d99a36264d0c22910cd966079ed`。公开1.7.0对照Setup SHA256 `7a6a54144875a58244d40c5ea8456a9535c21127eddeebf96e2bdfc069b044c6`。

- `diskfull-release-final/result.json`：1GiB临时NTFS VHD，观察到runtime替换后真实耗尽至空闲528384字节，退出5及真实磁盘I/O错误；旧runtime全部哈希恢复、旧版本注册表和用户数据保留、无runtime.previous，VHD已清理。
- `user-cancel-release-final/result.json`：真实非静默向导、正常用户取消日志、退出2；旧runtime全哈希、旧版本注册表、用户数据及无残留检查通过。旧轮次取消超时已由此成功记录取代。

## 最终构建与公开发布

Windows最新onefile/standalone构建及启动检查、Portable/Setup打包通过，见 `windows-gui-build-candidate.log`、`windows-gui-package-candidate.log`。Linux最终构建、打包与传输完成，`linux-build-candidate.log` 明确 `build_success=1`；deb为1.7.1-1，SHA256 `baa4f0fa1b85681ced815fbdc97fd23de4263c1a5e9b57247be5f7edbcf2284e`。旧暂停清单、旧矩阵、旧manifest不能冒充当前产物。

最终wheel说明元数据、Python sdist和外部Windows/Linux源码材料已刷新；Windows/Linux/sdist各135/123/142项公开源码对应发行标签工作区，26项wheel产品文件对应已测程序。公开归档461项文本秘密扫描为0，8项产物的版本、路径、内容身份、完整SHA256清单和文档链接只读核验通过，见`final-public-source-preflight.json`及`final-readonly-validation.json`。Setup内嵌SOURCES保留构建快照，最后工具/文档在外部源码包，33项Windows/32项Linux产品及安装输入一致，见[材料收尾说明](releasing.md#171-最终材料收尾)。

| 渠道 | 公开结果 |
| --- | --- |
| [GitHub v1.7.1](https://github.com/Koril33/bilix/releases/tag/v1.7.1) | 稳定版、latest=true；8项产物及manifest/SHA256SUMS全部10项从公开CDN完整回下载，大小和SHA256逐项通过（慢速请求超时后分段续取，最终始终核验完整文件）；`github-verification.json` |
| [PyPI 1.7.1](https://pypi.org/project/djhx-bilix/1.7.1/) | 官方元数据及wheel/sdist完整回下载哈希一致；两个全新Python3.11.2 CLI/GUI环境从官方索引安装，27项包文件/元数据与公开wheel逐字节一致，版本、blx/bilix、help/doctor、GUI Qt6.11.2与启动冒烟通过；CLI无Qt。GUI首次无缓存依赖下载超时后，只复用依赖缓存继续同一新建环境，项目包从官方索引刷新；超时记录保留 |
| Gitea | main与v1.7.1代码/标签同步；没有独立二进制发行镜像 |
| 网站 | 25项Chrome检查与48张截图通过，`site/bilix.html`随源码提交；维护者自行部署服务器 |

发行源码提交：`3a6a722d4e8473900b7c1a3cfc3caebf4d2ccf90`。公开PyPI验收：`public-pypi-171-20261009T133539Z-f5632541/result.json`。标签和发行文件不可变；公开渠道结果作为发布后的主分支补记，标签内归档保留发布前已完成的功能/候选验收快照。

| 发行文件 | 字节 | SHA256 |
| --- | ---: | --- |
| BiliX-GUI-Portable-1.7.1-windows-x64.exe | 33057792 | `f4a518a985de81f9d530640f2d4e794d29059222de390e8408c44815fb82fb5e` |
| BiliX-GUI-Setup-1.7.1-windows-x64.exe | 44594857 | `f2c816d2dabbb5f29ab8bc6bb2af5e57c6f59d99a36264d0c22910cd966079ed` |
| BiliX-GUI-licenses-and-source-1.7.1-windows-x64.zip | 13412376 | `9bb4eab3b0184df539a4041f05e69d8a2bbf24bc3f814b04df2540953ae21201` |
| bilix-1.7.1-windows-x64.zip | 29969263 | `2bb6675d765a582e59e9cdf44a01d703af3464fb4bce2890920b3383b9db06f3` |
| djhx-bilix-gui_1.7.1-1_amd64.deb | 66664760 | `baa4f0fa1b85681ced815fbdc97fd23de4263c1a5e9b57247be5f7edbcf2284e` |
| djhx-bilix-gui_1.7.1_source.tar.gz | 486035 | `a884157eba1890002245ed61290d9c1853b331f6e79bc7d83c96b077d2af411e` |
| djhx_bilix-1.7.1-py3-none-any.whl | 1790574 | `02a9c16a660162b4d36d3c366cc8fa6fcb450c9cc07cbe25bfc8918027f7a404` |
| djhx_bilix-1.7.1.tar.gz | 13485185 | `1bd0ca47de341695eb336332717213209e2444dc9e963558b3edc1645f176839` |

秘密预审 `secrets-preflight.log` 为工作区0项、历史22项，均为旧四个提交；[发布说明](releasing.md)已有维护者2026-10-03确认历史凭据失效的记录。不得写成历史扫描零项；私有token、VM状态、验收runtime和测试证据不进入发行归档。
