# Register the named Cloudflare tunnel to start reliably after Windows sign-in.
param(
    [string]$TaskName = "DeepMatter tunnel (user)",
    [string]$TunnelName = "anios",
    [string]$ConfigPath = (Join-Path $env:USERPROFILE ".cloudflared\config.yml"),
    [string]$CloudflaredPath = "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    [string]$RunnerPath = (Join-Path $PSScriptRoot "run-tunnel.ps1")
)

$ErrorActionPreference = "Stop"

# Confirm the executable and tunnel configuration exist before changing Task Scheduler.
function Test-TunnelPrerequisites {
    if (-not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) {
        throw "cloudflared was not found at $CloudflaredPath"
    }
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "Cloudflare tunnel config was not found at $ConfigPath"
    }
    if (-not (Test-Path -LiteralPath $RunnerPath -PathType Leaf)) {
        throw "Tunnel supervisor was not found at $RunnerPath"
    }
}

# Create a logon task that waits for networking and retries transient startup failures.
function Install-TunnelTask {
    $powershellPath = Join-Path $PSHOME "powershell.exe"
    $arguments = @(
        "-NoProfile"
        "-ExecutionPolicy Bypass"
        "-File `"$RunnerPath`""
        "-TunnelName `"$TunnelName`""
        "-ConfigPath `"$ConfigPath`""
        "-CloudflaredPath `"$CloudflaredPath`""
    ) -join " "
    $action = New-ScheduledTaskAction `
        -Execute $powershellPath `
        -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $trigger.Delay = "PT1M"
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -RunOnlyIfNetworkAvailable `
        -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal `
        -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Supervises the deep-matter.com connector to the local AniOS gateway." `
        -Force | Out-Null
}

Test-TunnelPrerequisites
Install-TunnelTask
Write-Output "Registered '$TaskName'. It starts one minute after sign-in and supervises the connector."
