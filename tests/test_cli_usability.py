import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from djhx_bilix import cli
from djhx_bilix.completion import COMPLETE_VAR, INPUT_VAR, Shell

runner = CliRunner()


def run_cli(arguments, *, env=None, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "djhx_bilix", *arguments],
        env={**os.environ, **(env or {})},
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


@pytest.mark.parametrize(
    "arguments,suggestion",
    [
        (["donwload"], "download"),
        (["inf"], "info"),
        (["auth", "stats"], "status"),
        (["auth", "logni"], "login"),
        (["--verison"], "--version"),
        (["download", "--quailty", "480p"], "--quality"),
        (["--quailty", "480p"], "--quality"),
    ],
)
def test_typos_suggest_without_running_a_command(arguments, suggestion, tmp_path):
    result = run_cli(arguments)
    assert result.returncode == 2, result.stderr
    assert suggestion in result.stderr
    assert "Did you mean" in result.stderr or "Possible options" in result.stderr
    assert not (tmp_path / "profile").exists()
    assert not (tmp_path / "downloads").exists()


def test_unrelated_unknown_command_has_no_guess():
    result = run_cli(["zzzzzzzz"])
    assert result.returncode == 2
    assert "No such command" in result.stderr
    assert "Did you mean" not in result.stderr


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (["BV1j4411W7F7", "--dry-run"], ["download", "BV1j4411W7F7", "--dry-run"]),
        (["https://b23.tv/abc"], ["download", "https://b23.tv/abc"]),
        (["--file", "urls.txt"], ["download", "--file", "urls.txt"]),
        (["--login"], ["auth", "login"]),
        (["completion", "bash"], ["completion", "bash"]),
    ],
)
def test_entry_keeps_legacy_inputs_and_new_completion(monkeypatch, arguments, expected):
    invocations = []
    monkeypatch.setattr(cli, "app", lambda **kwargs: invocations.append(kwargs["args"]))
    monkeypatch.setattr(sys, "argv", ["bilix.exe", *arguments])
    cli.main()
    assert invocations == [expected]


@pytest.mark.parametrize("shell", list(Shell))
@pytest.mark.parametrize("program", ["blx", "bilix", "bilix.exe"])
def test_completion_script_is_available_for_all_shells(shell, program):
    result = runner.invoke(cli.app, ["completion", shell.value], prog_name=program)
    assert result.exit_code == 0, result.output
    marker = (
        base64.b64encode(program.encode()).decode()
        if (shell in (Shell.powershell, Shell.pwsh))
        else program
    )
    assert marker in result.stdout and COMPLETE_VAR in result.stdout
    assert "Usage:" not in result.stdout
    assert "Set-ExecutionPolicy" not in result.stdout
    assert "Set-PSReadLineKeyHandler" not in result.stdout


@pytest.mark.parametrize(
    "words,expected,excluded",
    [
        (["blx", ""], {"download", "info", "auth", "completion"}, {"video", "user"}),
        (["blx", "do"], {"download", "doctor"}, {"info"}),
        (["blx", "auth", ""], {"login", "logout", "status"}, {"download"}),
        (["blx", "download", "--qu"], {"--quality", "--quiet"}, {"--file"}),
        (
            ["blx", "download", "--quality", "10"],
            {"1080p", "1080p+", "1080p60", "100"},
            {"720p", "auto"},
        ),
        (["blx", "download", "-q", "H"], {"HDR"}, {"auto"}),
        (["blx", "video", "--codec", "he"], {"HEVC"}, {"AVC"}),
        (["blx", "download", "--audio", ""], {"aac", "flac", "dolby", "best"}, {"AVC"}),
        (["blx", "download", "--page", "a"], {"all"}, {"1"}),
        (["blx", "download", "--quality", "bogus"], set(), {"auto"}),
    ],
)
def test_bash_completion_protocol_is_offline_and_filtered(words, expected, excluded, tmp_path):
    result = run_cli(
        [],
        env={
            COMPLETE_VAR: "complete_bash",
            "COMP_WORDS": " ".join(words),
            "COMP_CWORD": str(len(words) - 1),
        },
    )
    assert result.returncode == 0, result.stderr
    candidates = set(result.stdout.splitlines())
    assert expected <= candidates
    assert not excluded & candidates
    assert result.stderr == ""
    assert not (tmp_path / "profile").exists()
    assert not (tmp_path / "downloads").exists()


def test_generated_bash_script_in_a_real_shell():
    bash = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        candidate = Path(git).parent.parent / "bin" / "bash.exe" if git else None
        bash = str(candidate) if candidate and candidate.exists() else None
    if not bash:
        pytest.skip("Bash is not installed")
    generated = runner.invoke(cli.app, ["completion", "bash"], prog_name="blx")
    assert generated.exit_code == 0
    script = (
        generated.stdout
        + "\n"
        + "\n".join(
            [
                "COMP_WORDS='blx download --quality 1080'",
                "COMP_CWORD=3",
                "_blx_completion blx",
                "printf '%s\\n' \"${COMPREPLY[@]}\"",
            ]
        )
    )
    result = subprocess.run(
        [bash, "--noprofile", "--norc"],
        input=script,
        env={
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.splitlines()) == {"1080p", "1080p+", "1080p60"}
    assert result.stderr == ""


def test_powershell_json_preserves_unicode_spaces_quotes_and_backslashes(tmp_path):
    folder = tmp_path / "中文 空格"
    folder.mkdir()
    file = folder / "video's list.txt"
    file.write_text("BV1j4411W7F7", encoding="utf-8")
    result = run_cli(
        [],
        env={
            COMPLETE_VAR: "complete_powershell",
            INPUT_VAR: json.dumps(
                {"args": ["download", "--file"], "incomplete": str(folder / "vi")}
            ),
        },
    )
    assert result.returncode == 0, result.stderr
    assert f"{file}:::文件" in result.stdout
    assert result.stderr == ""


def test_save_completion_only_offers_directories(tmp_path):
    (tmp_path / "videos").mkdir()
    (tmp_path / "video.txt").touch()
    result = run_cli(
        [],
        cwd=tmp_path,
        env={
            COMPLETE_VAR: "complete_powershell",
            INPUT_VAR: json.dumps({"args": ["download", "--save"], "incomplete": "vi"}),
        },
    )
    assert result.returncode == 0, result.stderr
    assert f"videos{os.sep}:::目录" in result.stdout
    assert "video.txt" not in result.stdout


@pytest.mark.parametrize(
    "payload", ["bad json", "null", '{"args": 1}', '{"args": [1], "incomplete": ""}']
)
def test_malformed_completion_input_does_not_execute_a_command(payload, tmp_path):
    result = run_cli(
        ["auth", "login"],
        env={
            COMPLETE_VAR: "complete_powershell",
            INPUT_VAR: payload,
        },
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""
    assert not (tmp_path / "profile").exists()


@pytest.mark.parametrize("shell", ["pwsh", "powershell"])
def test_powershell_tab_completion_in_a_real_shell(tmp_path, shell):
    powershell = shutil.which(shell)
    launcher = Path(sys.executable).with_name("blx.exe")
    if os.name != "nt" or not powershell or not launcher.exists():
        pytest.skip("Windows PowerShell and the installed blx launcher are required")
    executable = tmp_path / "BiliX 测试's.exe"
    shutil.copy2(launcher, executable)
    generation = subprocess.run(
        [str(executable), "completion", shell],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert generation.returncode == 0, generation.stderr
    folder = tmp_path / "中文 空格"
    folder.mkdir()
    file = folder / "video's list.txt"
    file.touch()

    def quote(value):
        return "'" + value.replace("'", "''") + "'"

    lines = [
        f"& {quote(str(executable))} do",
        f"& {quote(str(executable))} auth sta",
        f"& {quote(str(executable))} download --quality 10",
        f"& {quote(str(executable))} download --codec he",
        f"& {quote(str(executable))} download --file {quote(str(folder / 'vi'))}",
        f"& {quote(str(executable))} download --quality bogus",
        f"& {quote(str(executable))} download --file {quote(str(file))} --qu",
    ]
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "[Console]::OutputEncoding = [System.Text.Encoding]::ASCII\n"
        f"(& {quote(str(executable))} completion {shell}) | Out-String | Invoke-Expression\n"
        + "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                "$env:_BILIX_COMPLETE = 'previous-mode'",
                "$env:_BILIX_COMPLETE_INPUT = 'previous-input'",
                "[Console]::OutputEncoding = [System.Text.Encoding]::ASCII",
                "$results = @()",
                *[
                    f"$line = {quote(line)}; $results += ,@("
                    "[System.Management.Automation.CommandCompletion]::CompleteInput("
                    "$line, $line.Length, $null).CompletionMatches | "
                    "ForEach-Object { $_.CompletionText })"
                    for line in lines
                ],
                f"$line = {quote(lines[2] + '80p --quiet')}",
                "$cursor = $line.IndexOf('1080p') + 3",
                "$results += ,@([System.Management.Automation.CommandCompletion]::CompleteInput("
                "$line, $cursor, $null).CompletionMatches | ForEach-Object { $_.CompletionText })",
                "$encoding = [Console]::OutputEncoding.WebName",
                "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()",
                "ConvertTo-Json -Depth 5 -Compress -InputObject @{ results = $results; "
                "mode = $env:_BILIX_COMPLETE; input = $env:_BILIX_COMPLETE_INPUT; "
                "encoding = $encoding }",
            ]
        )
    )
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert set(output["results"][0]) == {"download", "doctor"}
    assert output["results"][1] == ["status"]
    assert "1080p60" in output["results"][2]
    assert output["results"][3] == ["HEVC"]
    assert output["results"][4] == [quote(str(file))]
    assert output["results"][5] == []
    assert set(output["results"][6]) == {"--quality", "--quiet"}
    assert set(output["results"][7]) == {"1080p", "1080p+", "1080p60"}
    assert output["mode"] == "previous-mode" and output["input"] == "previous-input"
    assert output["encoding"] == "us-ascii"


@pytest.mark.parametrize("shell", ["pwsh", "powershell"])
def test_powershell_completion_for_bare_console_command(shell):
    powershell = shutil.which(shell)
    launcher = Path(sys.executable).with_name("blx.exe")
    if os.name != "nt" or not powershell or not launcher.exists():
        pytest.skip("Windows PowerShell and the installed blx launcher are required")
    program = str(launcher).replace("'", "''")
    script = (
        f"(& '{program}' completion {shell}) | Out-String | Invoke-Expression\n"
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()\n"
        "ConvertTo-Json -Compress -InputObject @{\n"
        " bare = @((TabExpansion2 -inputScript 'blx do' -cursorColumn 6)"
        ".CompletionMatches.CompletionText)\n"
        " extension = @((TabExpansion2 -inputScript 'blx.exe do' -cursorColumn 10)"
        ".CompletionMatches.CompletionText)\n}\n"
    )
    environment = os.environ.copy()
    environment["PATH"] = str(launcher.parent) + os.pathsep + environment.get("PATH", "")
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert set(output["bare"]) == {"download", "doctor"}
    assert set(output["extension"]) == {"download", "doctor"}
