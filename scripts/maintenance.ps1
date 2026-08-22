# Weekly upkeep: the growth nobody watches, bounded on a schedule.
#
# What users do cannot clog this machine - chat is text (the whole database
# is megabytes), context per turn is bounded, Redis state expires, and
# container logs are capped in compose. What DOES grow is operational:
# Docker's build cache swells with every deploy day (21GB in one evening,
# measured), rebuilds strand dangling images, and ComfyUI keeps every
# generated image forever in E:/AI/ComfyUI/output even though the backend
# copies each one into the artifact store seconds after generation - 864MB
# of redundant history at the time this was written.
#
# Registered as the weekly Task Scheduler job "AniOS Maintenance". Only
# anios_* files are pruned from ComfyUI's output, so anything a person
# makes with ComfyUI directly is never touched. Deletions stay conservative
# (7 days), because the artifact store is the system of record either way.

$ErrorActionPreference = "Continue"
$report = "E:\AgentWorkspace\PersonalAssistant\data\maintenance-report.txt"
"AniOS maintenance run: $(Get-Date -Format o)" | Out-File $report -Encoding utf8

# 1. Redundant ComfyUI outputs older than a week (the artifact store holds
#    the real copies; anios_* only).
$cutoff = (Get-Date).AddDays(-7)
$outputs = Get-ChildItem "E:\AI\ComfyUI\output" -Filter "anios_*" -File |
    Where-Object { $_.LastWriteTime -lt $cutoff }
$freed = ($outputs | Measure-Object Length -Sum).Sum
$outputs | Remove-Item -Force -Confirm:$false
"comfyui outputs pruned: $($outputs.Count) files, $([math]::Round($freed/1MB,1)) MB" |
    Out-File $report -Append -Encoding utf8

# 2. Docker's deploy debris: build cache beyond a working margin, dangling
#    images from rebuilds.
docker builder prune -f --keep-storage 5GB 2>&1 | Select-Object -Last 1 |
    Out-File $report -Append -Encoding utf8
docker image prune -f 2>&1 | Select-Object -Last 1 |
    Out-File $report -Append -Encoding utf8

# 3. Visibility: the numbers worth a quarterly glance, in one place. The
#    artifact volume is deliberately reported and never pruned - generated
#    and uploaded images are user data and their retention is the
#    operator's call, not a script's.
"--- sizes ---" | Out-File $report -Append -Encoding utf8
docker system df 2>&1 | Out-File $report -Append -Encoding utf8
docker exec anios_db psql -U postgres -d anios_db -t -c "SELECT 'database: ' || pg_size_pretty(pg_database_size('anios_db'))" 2>&1 |
    Out-File $report -Append -Encoding utf8
"comfyui output now: $([math]::Round(((Get-ChildItem 'E:\AI\ComfyUI\output' -File | Measure-Object Length -Sum).Sum)/1MB,1)) MB" |
    Out-File $report -Append -Encoding utf8

Get-Content $report
