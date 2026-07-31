# Start the whole AniOS stack with one command, including the local ComfyUI
# image backend.
#
#   powershell -ExecutionPolicy Bypass -File scripts\start-anios.ps1
#
# ComfyUI runs on the host (using the install at COMFYUI_HOST_PATH) because the
# backend targets host.docker.internal:8188 and the host path is far lighter than
# the GPU container image. To use the containerized ComfyUI instead, skip the
# host step below and run: docker compose --profile comfyui up -d

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

# Read one non-secret operator setting from the local environment file.
function Get-EnvValue([string]$name, [string]$fallback) {
    $envFile = Join-Path $root '.env'
    if (Test-Path $envFile) {
        $match = Select-String -Path $envFile -Pattern "^\s*$name\s*=" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($match) {
            $value = ($match.Line -split '=', 2)[1].Trim()
            if ($value) { return $value }
        }
    }
    return $fallback
}

# Report whether a loopback service is accepting TCP connections.
function Test-Port([int]$port) {
    try {
        $client = New-Object Net.Sockets.TcpClient
        $client.Connect('127.0.0.1', $port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

# Compile one bounded generation and embedding path before user traffic arrives.
function Invoke-VllmWarmup {
    $mainBody = @{
        model = 'qwen/qwen3.5-4b'
        messages = @(@{ role = 'user'; content = 'Reply with exactly READY' })
        max_tokens = 16
        temperature = 0
        reasoning_effort = 'none'
    } | ConvertTo-Json -Depth 5 -Compress
    Invoke-RestMethod `
        -Uri 'http://127.0.0.1:8003/v1/chat/completions' `
        -Method Post `
        -ContentType 'application/json' `
        -Body $mainBody | Out-Null

    $embeddingBody = @{
        model = 'text-embedding-nomic-embed-text-v1.5'
        input = @('search_document: AniOS startup warmup')
    } | ConvertTo-Json -Depth 3 -Compress
    Invoke-RestMethod `
        -Uri 'http://127.0.0.1:8004/v1/embeddings' `
        -Method Post `
        -ContentType 'application/json' `
        -Body $embeddingBody | Out-Null
}

# 1) Initialize vLLM in the measured VRAM-safe order. The embedding service
# waits for the main generation/VLM service to become healthy in Compose.
Write-Host 'Starting vLLM services ...'
docker compose -f (Join-Path $root 'docker-compose.yml') up -d --wait --wait-timeout 900 vllm-main vllm-embedding

# 2) Pay one-time JIT costs before the first user request.
Write-Host 'Warming vLLM generation and embedding paths ...'
Invoke-VllmWarmup

# 3) ComfyUI on the host, unless something already listens on 8188. Starting it
# after vLLM avoids competing with CUDA graph and KV-cache initialization.
if (Test-Port 8188) {
    Write-Host 'ComfyUI already running on :8188.'
} else {
    $comfy = Get-EnvValue 'COMFYUI_HOST_PATH' 'E:/AI/ComfyUI'
    $python = $null
    foreach ($candidate in @("$comfy\.venv\Scripts\python.exe", "$comfy\python_embeded\python.exe")) {
        if (Test-Path $candidate) { $python = $candidate; break }
    }
    if (-not $python) { $python = 'python' }

    if (-not (Test-Path (Join-Path $comfy 'main.py'))) {
        Write-Warning "ComfyUI not found at $comfy. Set COMFYUI_HOST_PATH in .env; image generation will be unavailable until it runs."
    } else {
        Write-Host "Starting ComfyUI from $comfy ..."
        Start-Process -FilePath $python `
            -ArgumentList 'main.py', '--listen', '0.0.0.0', '--port', '8188', '--disable-auto-launch' `
            -WorkingDirectory $comfy -WindowStyle Hidden
    }
}

# 4) Start the remaining application services after inference is ready.
Write-Host 'Starting AniOS application services ...'
docker compose -f (Join-Path $root 'docker-compose.yml') up -d

# 5) Wait for the backend, then report.
Write-Host -NoNewline 'Waiting for backend '
for ($i = 0; $i -lt 40; $i++) {
    try {
        $response = Invoke-WebRequest -Uri 'http://localhost:8000/health' -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200) { break }
    } catch { }
    Write-Host -NoNewline '.'
    Start-Sleep -Seconds 3
}
Write-Host ''

Write-Host ''
Write-Host 'AniOS is up:'
Write-Host '  Frontend  http://localhost:5173'
Write-Host '  API       http://localhost:8000  (docs at /docs)'
if (Test-Port 8188) {
    Write-Host '  ComfyUI   http://localhost:8188  (image generation ready)'
} else {
    Write-Host '  ComfyUI   not detected on :8188 - image generation will be unavailable.'
}
