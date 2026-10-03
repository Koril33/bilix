"""Offline shell completion helpers and scripts."""

import base64
import json
import os
import shlex
from enum import StrEnum
from pathlib import Path

from typer.completion import get_completion_script

from .models import QUALITY_NAMES

COMPLETE_VAR = "_BILIX_COMPLETE"
INPUT_VAR = "_BILIX_COMPLETE_INPUT"


class Shell(StrEnum):
    bash = "bash"
    zsh = "zsh"
    fish = "fish"
    powershell = "powershell"
    pwsh = "pwsh"


def complete_quality(incomplete: str):
    choices = [("auto", "当前账号可获取的最高画质"), ("best", "同 auto")]
    for quality, name in QUALITY_NAMES.items():
        choices.extend([(name.lower(), f"清晰度 {quality}"), (str(quality), name)])
    return [
        (incomplete + (value.upper() if incomplete.isupper() else value)[len(incomplete) :], help)
        for value, help in choices
        if value.startswith(incomplete.lower())
    ]


def complete_page(incomplete: str):
    return (
        [(incomplete + "all"[len(incomplete) :], "全部选集")]
        if ("all".startswith(incomplete.lower()))
        else []
    )


def complete_path(incomplete: str, *, directories_only: bool = False):
    # Enumerate local paths ourselves: Typer's PowerShell protocol discards path types.
    expanded = os.path.expanduser(incomplete)
    parent, prefix = os.path.split(expanded)
    try:
        candidates = sorted(Path(parent or ".").iterdir(), key=lambda path: path.name.casefold())
        result = []
        for path in candidates:
            matches = (
                path.name.casefold().startswith(prefix.casefold())
                if os.name == "nt"
                else (path.name.startswith(prefix))
            )
            if not matches or (path.name.startswith(".") and not prefix.startswith(".")):
                continue
            directory = path.is_dir()
            if directories_only and not directory:
                continue
            value = incomplete + path.name[len(prefix) :]
            if directory:
                value += os.sep
            result.append((value, "目录" if directory else "文件"))
        return result
    except OSError:
        return []


def complete_file(incomplete: str):
    return complete_path(incomplete)


def complete_directory(incomplete: str):
    return complete_path(incomplete, directories_only=True)


def shell_script(prog_name: str, shell: Shell) -> str:
    if shell not in (Shell.powershell, Shell.pwsh):
        return get_completion_script(
            prog_name=prog_name, complete_var=COMPLETE_VAR, shell=shell.value
        )
    # Use the PowerShell AST and JSON to preserve spaces, backslashes and quotes.
    # Scope environment changes to this call and leave PSReadLine preferences alone.
    # Keep generated source ASCII even when PowerShell decodes native output as ANSI.
    program = base64.b64encode(prog_name.encode("utf-8")).decode("ascii")
    return r"""$bilixProgram = [System.Text.Encoding]::UTF8.GetString(
    [System.Convert]::FromBase64String('__PROGRAM__'))
$bilixCompleter = {
    param($wordToComplete, $commandAst, $cursorPosition)
    $arguments = @()
    $incomplete = ''
    foreach ($element in ($commandAst.CommandElements | Select-Object -Skip 1)) {
        if ($element.Extent.StartOffset -ge $cursorPosition) { break }
        $value = $element.Extent.Text
        if ($element -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
            $value = $element.Value
        }
        if ($element.Extent.EndOffset -ge $cursorPosition) {
            if ($element.Extent.EndOffset -gt $cursorPosition) {
                $length = $cursorPosition - $element.Extent.StartOffset
                $value = $element.Extent.Text.Substring(0, $length)
                if ($value.StartsWith("'")) { $value = $value.Substring(1).Replace("''", "'") }
                elseif ($value.StartsWith('"')) { $value = $value.Substring(1) }
            }
            $incomplete = $value
            break
        }
        $arguments += $value
    }
    $previousMode = $env:_BILIX_COMPLETE
    $previousInput = $env:_BILIX_COMPLETE_INPUT
    $previousEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
        $env:_BILIX_COMPLETE = 'complete_powershell'
        $env:_BILIX_COMPLETE_INPUT = ConvertTo-Json -Compress -InputObject @{
            args = @($arguments); incomplete = $incomplete
        }
        & $bilixProgram | ForEach-Object {
            if ([string]::IsNullOrEmpty($_)) { return }
            $parts = $_ -split ':::', 2
            $value = $parts[0]
            if ($value -match '[\s''`$;&|(){}\[\]<>@#]') {
                $value = "'" + $value.Replace("'", "''") + "'"
            }
            [System.Management.Automation.CompletionResult]::new(
                $value, $parts[0], 'ParameterValue', $parts[1])
        }
    } finally {
        $env:_BILIX_COMPLETE = $previousMode
        $env:_BILIX_COMPLETE_INPUT = $previousInput
        [Console]::OutputEncoding = $previousEncoding
    }
}.GetNewClosure()
$bilixCommands = @($bilixProgram, [System.IO.Path]::GetFileName($bilixProgram),
    [System.IO.Path]::GetFileNameWithoutExtension($bilixProgram)) |
    Select-Object -Unique
Register-ArgumentCompleter -Native -CommandName $bilixCommands -ScriptBlock $bilixCompleter
""".replace("__PROGRAM__", program).strip()


def prepare_powershell_input() -> bool:
    """Translate the generated script's JSON into Typer's completion protocol."""
    if os.environ.get(COMPLETE_VAR) != "complete_powershell" or INPUT_VAR not in os.environ:
        return True
    try:
        payload = json.loads(os.environ[INPUT_VAR])
        arguments, incomplete = payload["args"], payload["incomplete"]
        if not isinstance(arguments, list) or not all(isinstance(arg, str) for arg in arguments):
            return False
        if not isinstance(incomplete, str):
            return False
    except (ValueError, KeyError, TypeError):
        return False
    words = ["bilix", *arguments, *([incomplete] if incomplete else [])]
    os.environ["_TYPER_COMPLETE_ARGS"] = shlex.join(words)
    os.environ["_TYPER_COMPLETE_WORD_TO_COMPLETE"] = incomplete
    return True
