# Keep the named Cloudflare connector alive across transient network and process failures.
param(
    [string]$TunnelName = "anios",
    [string]$ConfigPath = (Join-Path $env:USERPROFILE ".cloudflared\config.yml"),
    [string]$CloudflaredPath = "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    [int]$RetrySeconds = 15
)

$ErrorActionPreference = "Continue"

# Run cloudflared in the foreground and relaunch it whenever it exits.
function Start-TunnelSupervisor {
    while ($true) {
        & $CloudflaredPath --config $ConfigPath tunnel --no-autoupdate run $TunnelName
        $exitCode = $LASTEXITCODE
        Write-Warning "cloudflared exited with code $exitCode; retrying in $RetrySeconds seconds."
        Start-Sleep -Seconds $RetrySeconds
    }
}

if (-not (Test-Path -LiteralPath $CloudflaredPath -PathType Leaf)) {
    throw "cloudflared was not found at $CloudflaredPath"
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Cloudflare tunnel config was not found at $ConfigPath"
}

Start-TunnelSupervisor
