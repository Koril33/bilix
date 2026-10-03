# Tab 补全与指令纠错

该功能从 1.5.0 引入；旧版本需要先升级：`uv tool upgrade djhx-bilix`，或下载新的 Windows 发行包。源码环境可使用 `uv run blx`。


Tab 补全支持命令、`auth` 子命令、选项、清晰度名称/id、编码、音轨、`--page all`，以及 `--file`、`--save`、`--ffmpeg` 的本地路径。补全按已输入的前缀过滤，不访问网络或读取登录凭据；选集数字和范围仍按实际需要输入。

先为当前终端启用补全。下面以 `blx` 为例，使用 `bilix` 时将脚本生成命令中的 `blx` 替换为 `bilix`，两个命令名分别注册。`blx completion SHELL` 仅输出脚本。

PowerShell（Windows PowerShell 5.1 和 PowerShell 7）：

```powershell
blx completion powershell | Out-String | Invoke-Expression
# 使用独立 exe 时：
.\bilix.exe completion powershell | Out-String | Invoke-Expression
```

如需每次打开 PowerShell 都启用，将 `(& blx completion powershell) | Out-String | Invoke-Expression` 加入 `$PROFILE`；exe 则使用实际路径，例如 `(& 'C:\Tools\bilix.exe' completion powershell) | Out-String | Invoke-Expression`。脚本保留现有 Tab 按键设置与执行策略；Tab 的候选展示方式取决于终端设置。

Bash、Zsh、Fish：

```bash
# Bash，持久启用时将此行加入 ~/.bashrc
eval "$(blx completion bash)"
# Zsh，持久启用时在 ~/.zshrc 的 compinit 初始化之后加入此行
eval "$(blx completion zsh)"
# Fish，持久启用时将此行加入 ~/.config/fish/config.fish
blx completion fish | source
```

例如输入 `blx do<Tab>` 可补全 `download` / `doctor`，`blx auth <Tab>` 提示登录相关子命令，`blx download --qu<Tab>` 提示 `--quality` / `--quiet`，`blx download -q 1080<Tab>` 提示对应清晰度。Windows CMD 没有这套参数补全接口，请使用 PowerShell。`python -m djhx_bilix completion SHELL` 生成的脚本默认注册已安装的 `blx`。

拼错命令或选项时，CLI 提示相近的正确写法，例如 `blx donwload` 提示 `download`，`blx auth stats` 提示 `status`，`blx download --quailty 480p` 提示 `--quality`。提示后返回参数错误退出码 `2`，由用户修改后再执行。

## 常见问题

- 没有候选：在当前终端加载生成的脚本，并确认命令来自同一个安装环境。
- exe 未加入 PATH：在 exe 所在目录或通过完整路径生成脚本；PowerShell 脚本记录实际路径。移动 exe 后重新生成。
- Zsh 报 `compdef` 不存在：先执行 `autoload -Uz compinit; compinit`。
- 路径含空格/单引号：PowerShell 使用 AST/JSON 保留参数，并为候选生成引号。
- 光标在命令中间：PowerShell 仅使用光标之前的参数前缀。

Tab 的循环/菜单显示由终端决定。新脚本不更改执行策略或 PSReadLine 按键。推荐使用 `completion SHELL`；`--install-completion` 保留 Typer 自带安装逻辑。
