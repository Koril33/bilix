# 1.7.1 最终材料收尾（历史）

以下保留当版发布收尾记录，不能用作当前操作步骤。当前流程见 [releasing.md](../releasing.md)，完整结果见 [validation-1.7.1.md](../validation-1.7.1.md)。

### 1.7.1 最终材料收尾

本轮最终二进制的输入已冻结，最后变更只涉及版本验证工具、桌面验收驱动和文档。刷新源码材料前逐文件核对 Windows 的33项产品、入口、安装器及许可/项目输入，Linux对应32项（不含Windows内置 `src/djhx_bilix/assets/ffmpeg.exe`）；预审记录为 `build/release-1.7.1/final-source-refresh-input-precheck.json`。产品、锁文件、安装器脚本与冻结样本须保持一致，不能以版本号相同替代内容对应。

Windows Setup 内嵌的 `SOURCES` 保留实际打包时的源码快照；外部配套源码ZIP更新最后的工具与文档，并保持运行依赖许可及FFmpeg材料原字节。Linux外部源码包与Python sdist也刷新至最终公开工作区。此次材料收尾不重建已验收的Setup、Portable、deb或CLI程序，不宣称安装器内嵌文档也已更新。发布时将外部源码包与二进制一并提供，记录两个源码快照的差别及一致的产品输入。

README作为Python包的长说明进入METADATA/PKG-INFO，最终文档冻结后重建wheel与sdist，核对长说明和版本；与已通过318项的wheel逐文件比较产品字节，再以实际安装做身份与GUI启动冒烟。只改包说明不扩大为全量或平台二进制重验。源码归档、公开文本秘密扫描和最终清单均须针对刷新后的产物执行；最终事实与哈希见 [1.7.1 验收记录](../validation-1.7.1.md)。
