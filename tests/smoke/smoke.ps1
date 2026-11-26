# Windows smoke test for dore: install from a local copy of the repo, then save and recall a fact
# through the real Claude Code hook command (run by Git Bash, as Claude Code does on Windows).
#
#   powershell -ExecutionPolicy Bypass -File tests\smoke\smoke.ps1
#
# Needs Node 18+, Git for Windows and Claude Code. Uses its own dore folder (%TEMP%\dore-smoke),
# so it does not touch a real dore install. Nothing is published or pushed.
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$env:DORE_HOME = Join-Path $env:TEMP "dore-smoke"
$env:DORE_PIP_SPEC = $Repo
$env:DORE_MARKETPLACE = $Repo
$results = @()
function Check($name, $ok, $detail) {
    $script:results += [pscustomobject]@{ Check = $name; Result = $(if ($ok) { "PASS" } else { "FAIL" }); Detail = $detail }
}

Write-Host "== 1. install (from $Repo)"
if (Test-Path $env:DORE_HOME) { Remove-Item -Recurse -Force $env:DORE_HOME }
$t = Measure-Command { node "$Repo\npm\bin\dore-memory.js" install | Out-Host }
$hook = Join-Path $env:DORE_HOME ".venv\Scripts\dore-hook.exe"
Check "install" (Test-Path $hook) ("{0:N0} s" -f $t.TotalSeconds)

Write-Host "== 2. hook command through Git Bash"
$bash = @("$env:ProgramFiles\Git\bin\bash.exe", "${env:ProgramFiles(x86)}\Git\bin\bash.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $bash) { Check "git bash" $false "Git for Windows not found"; $results | Format-Table -AutoSize; exit 1 }
$hooks = Get-Content "$Repo\plugin\hooks\hooks.json" -Raw | ConvertFrom-Json
$cmd = $hooks.hooks.UserPromptSubmit[0].hooks[0].command
# Hand the command to Git Bash in a file: Windows PowerShell 5 mangles quotes inside native arguments.
$cmdFile = Join-Path $env:TEMP "dore-smoke-hook.sh"
[IO.File]::WriteAllText($cmdFile, $cmd + "`n")
$project = Join-Path $env:TEMP "dore-smoke-project"
New-Item -ItemType Directory -Force $project | Out-Null

function Send-Prompt($text, $session) {
    $json = @{ prompt = $text; session_id = $session; cwd = $project; hook_event_name = "UserPromptSubmit" } | ConvertTo-Json -Compress
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $out = $json | & $bash $cmdFile 2>&1 | Out-String
    $sw.Stop()
    return @{ Out = $out; Seconds = $sw.Elapsed.TotalSeconds }
}

$r1 = Send-Prompt "Our billing service runs on port 6200." "smoke-1"
Check "first prompt under 20 s (Claude Code's hook limit)" ($r1.Seconds -lt 20) ("{0:N1} s" -f $r1.Seconds)
$r2 = Send-Prompt "What port does the billing service use?" "smoke-2"
Check "recall in a new session" ($r2.Out -match "6200") ("{0:N1} s" -f $r2.Seconds)
$warm = @(1..3 | ForEach-Object { (Send-Prompt "What port does the billing service use?" "smoke-w$_").Seconds })
Check "warm helper (127.0.0.1 + token)" (($warm | Measure-Object -Minimum).Minimum -lt 1) (($warm | ForEach-Object { "{0:N2}" -f $_ }) -join " / " + " s")
Check "helper port file" (Test-Path (Join-Path $env:DORE_HOME "data\hook.sock")) "data\hook.sock"

Write-Host "== 3. status and uninstall"
node "$Repo\npm\bin\dore-memory.js" status | Out-Host
node "$Repo\npm\bin\dore-memory.js" uninstall | Out-Host
Check "uninstall keeps memory" ((-not (Test-Path (Join-Path $env:DORE_HOME ".venv"))) -and (Test-Path (Join-Path $env:DORE_HOME "data\memory.db"))) ""
Check "uninstall stopped the helper" (-not (Test-Path (Join-Path $env:DORE_HOME "data\hook.sock"))) ""

$results | Format-Table -AutoSize
if ($results.Result -contains "FAIL") { exit 1 }
