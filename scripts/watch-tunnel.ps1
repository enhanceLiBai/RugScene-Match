# 保留已经运行的项目临时隧道；仅在进程退出后重新启动。
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$executable = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$target = 'http://127.0.0.1:8000'
$logs = Join-Path $root 'runtime-logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stderrLog = Join-Path $logs 'tunnel-stderr.log'
$stdoutLog = Join-Path $logs 'tunnel-stdout.log'
$urlFile = Join-Path $logs 'tunnel-url.txt'
$watchLog = Join-Path $logs 'tunnel-watch.log'
$healthUrl = 'http://127.0.0.1:8000/health'
if (-not (Test-Path -LiteralPath $executable)) { throw 'cloudflared 未安装在预期位置。' }

while ($true) {
    $backendHealthy = $false
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3
        $backendHealthy = $response.StatusCode -eq 200
    } catch {
        $backendHealthy = $false
    }
    $running = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" |
        Where-Object { $_.ExecutablePath -eq $executable -and $_.CommandLine -match '--url\s+"?http://127\.0\.0\.1:8000(?:"|\s|$)' }
    if (-not $backendHealthy) {
        if ($running) {
            $running | ForEach-Object {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
            Add-Content -LiteralPath $watchLog -Value "$(Get-Date -Format o) Backend unhealthy; stopped tunnel for reconnect"
        }
        [System.IO.File]::WriteAllText($urlFile, '后台服务不可用，隧道等待后台恢复后重连。')
        Start-Sleep -Seconds 10
        continue
    }
    if (-not $running) {
        # 后台恢复后重新建立隧道；临时隧道重启后地址会变化。
        [System.IO.File]::WriteAllText($urlFile, '隧道正在重新连接，新地址生成后会更新。')
        $child = Start-Process -FilePath $executable -ArgumentList 'tunnel','--url',$target -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
        Add-Content -LiteralPath $watchLog -Value "$(Get-Date -Format o) Started tunnel PID=$($child.Id)"
    }
    if (Test-Path -LiteralPath $stderrLog) {
        $address = Select-String -LiteralPath $stderrLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' |
            Select-Object -Last 1
        if ($address) { [System.IO.File]::WriteAllText($urlFile, $address.Matches[0].Value) }
    }
    Start-Sleep -Seconds 10
}
