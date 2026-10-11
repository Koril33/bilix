# 1.7.6 更新功能验收与发布记录

日期：2026-10-11（Asia/Shanghai）。状态：**验收通过，1.7.6 已公开发布，公开下载复验通过**。维护者要求本版对更新功能做较全面验收后发布。

本版新增 GUI 更新器、Ed25519 签名与双源发布、固定 Linux 提权入口和签名 APT 源。下载内核及 CLI 行为没有功能改动。基线为已发布的 1.7.5；旧客户端没有更新器，旧版手动升级与更新器完整事务分别验收。

## 自动回归和问题修复

- Windows CPython 3.14.8 / PySide6 6.11.2：完整 GUI profile **403 passed、0 skip**，Ruff 与 93 份 Python 文件格式检查通过。CLI 入口/帮助/版本/doctor/参数错误、四种补全与 GUI 自检通过。
- 最低版本 CPython 3.11.2 独立安装候选 wheel：CLI profile **305 passed、0 skip**，环境不含 Qt/cryptography；GUI profile **403 passed、0 skip**。另验证当前允许的 CLI 依赖组合。
- Ubuntu 22.04 / CPython 3.14.8：**397 passed、6 skip**；跳过项是 GUI scripts、四种 PowerShell 补全和 Windows 控制台事件，均有上述 Windows 对应通过结果。
- 新增真实私有 HTTPS 服务的 10 项传输检查：主源 503/签名失效/截断与备用源回退、正常主源、不受信 CA、HTTPS 降级、大小上限、取消/临时文件清理和同大小 SHA256 篡改；使用测试 CA 与临时签名密钥，不关闭 TLS 校验。
- 修复绿色版新 EXE 不能创建进程时未进入恢复路径的问题；现在恢复上一 EXE，并且只重启一次。
- 修复 Windows 更新缓存锁读取已锁字节时返回泛化权限错误的问题；第二实例能够得到明确的准备冲突提示。
- deb 改为显式 xz 压缩：真实 aptly 1.4 无法导入最初的默认 zstd control 归档，修正后成功生成签名源；未公开失败候选。

## 实际打包、更新和系统安装

- 最终 Windows GUI onefile/standalone 与 Ubuntu 22.04 GUI 冻结程序启动自检通过，中文/空格路径通过；Windows CLI 在独立无 Qt 环境构建，编译报告排除 Qt/updater/cryptography。
- Windows 10 22H2 build 19045.6466：正式 1.7.5 Setup → 本版真实安装器升级、同版本重装、卸载及配置/下载文件保留通过；两个绿色版启动与安装后启动通过。
- 实际冻结协调器的绿色升级成功、上一 EXE 哈希保留、文件占用、另一个实例、无效签名、篡改包和新 EXE 无法启动后的恢复通过。目标使用改名及中文/空格路径，签名夹具只放在忽略目录，未发布。
- 安装版协调器通过真实 Inno 向导更新、普通用户重启和新版启动标记确认；取消向导返回失败/未安装、旧运行时保留。另用当前 Inno 模板的私有坏 EXE 夹具验证：安装成功而启动失败记录 `installed: true`，提示人工恢复，不谎报更新成功或擅自恢复旧安装版。
- Ubuntu 22.04 可见 X11 桌面，从生产窗口更新按钮交接真实冻结协调器，经 polkit 窗口授权安装私有 `1.7.6-2` 测试 revision，启动标记与普通用户 UID 1000 确认通过；取消授权保留 `1.7.6-1`、下载包及普通用户旧 GUI。测试后恢复正式 `1.7.6-1`，临时管理员测试密码已恢复。测试 revision 没有上传服务器或 APT 源。
- 已安装的固定 root 冻结入口实际拒绝同 revision、未知签名、同大小篡改 deb、包符号链接及 FIFO 元数据，五项均保留原安装版本。真实 root 复制后验证与系统 APT 安装，与模拟单元测试分开记录。

| 系统 | 最终 deb 安装/1.7.5→1.7.6/重装/卸载/数据保留 | offscreen 与 Xvfb xcb 启动 | 公网 Signed-By 源/1.7.5→1.7.6 |
| --- | --- | --- | --- |
| Ubuntu 22.04 | 通过 | 通过 | 通过 |
| Ubuntu 24.04 | 通过 | 通过 | 通过 |
| Debian 12 | 通过 | 通过 | 通过 |
| Debian 13 | 通过 | 通过 | 通过 |

四发行版验收复用专用 VM，不称为新建的干净镜像。Ubuntu 24.04 首轮因旧 VM 缺失 APT 索引无法查到新增依赖，刷新系统索引后通过；包验收脚本现在先执行 `apt-get update`。Ubuntu 22.04 的可见桌面另在构建 VM 验证；安装 VM 的 Xvfb 结果不冒充可见桌面。Windows 在真实登录桌面复验向导；服务会话、旧死锁文件及向导自动化错误的中间失败均保留为诊断，只采用最终成功记录。

## 在线业务、签名与发布基础设施

- 正式 Windows CLI 未登录账号实际下载 BV1j4411W7F7 的 P1 / 360p，完成媒体校验与音视频合并，1 项完成、0 失败；输出 5,326,333 字节，完整系统 FFmpeg 全片解码退出 0。未重测真实会员/扫码登录、全量 IME/DPI 和 Wayland；本轮重点是更新，不把既有版本的这些结果写成本轮通过。
- 官网本地页面 25 项桌面/移动端、GitHub API 回退与减少动画检查通过。
- 应用 Ed25519 受保护备份恢复后与内置公钥匹配，并完成签名验证；独立 APT GPG 备份在新 keyring 中导入、签名及验证通过。APT 指纹 `201A20E104EF3C72CE573F7E61323BAA3BB87821`，Windows 私有目录另有受保护备份。未验证异地离线介质。
- Nginx 已部署资源专用 location，`nginx -t` 与平滑 reload 通过，缺失更新资源实际 HTTP 404，不返回首页 HTML 200。APT 源已上线，59 份公开索引/公钥/pool/by-hash 文件上传前后 SHA256 核对；四发行版实际验证其签名并从公网安装升级。服务器仅有公钥/签名，不持有应用或 APT 私钥。
- 工作树秘密扫描 **0 项**；历史仍为此前已确认撤销凭据的 **22 项**，未增加新发现或擅自重写历史。文档本地链接检查通过；完整归档/许可/对应源码与最终公开回下载结果见下文。

## 发行收尾

Windows 当前 Inno 模板另完成真实 I/O 故障验收：运行目录写入后缺失外部文件，安装返回 5；全部旧运行文件的逐项 SHA256、1.7.5 安装记录恢复，未残留 `runtime.previous`。占用旧 EXE 时安装返回 3，旧文件及版本记录保持一致。最终记录 `windows-final-results.json` 中 `installer-failure-da047905346046a699afb1bcf18c797a` 通过。故障专用安装包从未进入公开发行。

CLI ZIP 的配套材料继续使用 GPL、FFmpeg 对应源码和许可；GUI 新增 cryptography 的 Apache/BSD notices。

## 最终公开发布与回验

- 产品提交 `326a8ab0e4c45d2131290c6e0cb01338631395d4`，标签 `v1.7.6`，已同步 GitHub/Gitea。发行的八项产物完成大小/SHA256、包身份、安全归档路径与必需许可/源码材料检查；签名清单在三种 GUI 安装形式下均通过内置公钥验证。
- Windows 许可/源码 ZIP、Linux 源码 tar.gz 和 Python sdist 分别对照标签核对 **189 / 177 / 196** 份源码文件（文本统一换行后比较）。50 份产品源文件与冻结时快照一致；最终测试过的 Portable、Setup 和 deb 字节没有重包。外部源码包补全最终验收工具和文档，冻结程序内置源码保留构建时快照。本文的发布后追加记录不回写已经公开的源码包或标签。
- [GitHub v1.7.6](https://github.com/Koril33/bilix/releases/tag/v1.7.6) 是最新正式版。八项产物、汇总清单/校验文件和五份更新元数据/公钥，共 **15 份**，均匿名完整下载并核对 SHA256；`github-verification.json` 留存记录。CDN 个别分片超时重试后通过。
- [官网](https://bilix.djhx.site/) 的 `/releases/v1.7.6/` 同样 **15 份**公开文件完整下载、逐项哈希一致；三种 GUI 的公开元数据验签通过，`/updates/stable.json` 和签名与本地冻结内容相同，序号 **1**。缺失渠道文件仍为 HTTP 404。记录 `mirror-verification.json`；当前验收代理的大文件阻塞通过直接 HTTPS/有界分段复验处理，临时验证脚本的文件关闭后改名问题也已修正，未修改产品代理行为。
- 在独立进程仅模拟本地版本为 1.7.5，正式客户端逻辑实际从不可达 GitHub 回退官网，完成公网 Portable 整包下载、大小/SHA256、签名及缓存重新校验；没有调用安装或替换。恢复本地版本为 1.7.6 后，实际检查返回无更新。记录 `live-client-verification.json`；本项使用直接 HTTPS，原生冻结程序的安装/恢复事务另由前述平台记录覆盖。
- [PyPI 1.7.6](https://pypi.org/project/djhx-bilix/1.7.6/) 的 wheel/sdist 两文件完整下载，哈希与发行相同。元数据最低 Python 3.11 和 GUI extra 正确；在独立 CPython 3.11.2 环境重新安装公开下载 wheel，CLI 版本与 GUI 离线启动通过，pip 环境没有冻结更新身份。记录 `pypi-verification.json`、`public-wheel-smoke.json`。
- 官网 `index.html` 已部署，公网 HTTP 200 的全部字节与标签中的 `site/bilix.html` 一致，SHA256 `34ceb4e02dce9e4913d6ca06cbdb63e91ec15d6b50c831a85cf7c7926e5785f7`；备用下载入口、APT 地址及完整指纹可见。原站点与 Nginx 配置备份保留，部署检查见 `site-public-verification.json`。
- 专用 Linux 验收 VM 已停止；Windows 临时验证任务及一次性凭据文件已清理。发布后只同步文档记录，产品代码、版本标签与所有公开发行字节保持不变。

完整产物哈希由最终 `release-manifest.json`、`SHA256SUMS.txt` 与签名清单记录，避免源码包中的本文产生自引用哈希。证据保存在忽略目录 `build/release-1.7.6/`、`build/validation/1.7.6/` 与 `dist/gui/validation/`。
