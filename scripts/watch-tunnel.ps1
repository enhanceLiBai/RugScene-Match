# 保留已经运行的项目临时隧道；仅在进程退出后重新启动。
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$executable = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
$target = 'http://127.0.0.1:8000'
$protocol = 'http2'
$logs = Join-Path $root 'runtime-logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stderrLog = Join-Path $logs 'tunnel-stderr.log'
$stdoutLog = Join-Path $logs 'tunnel-stdout.log'
$urlFile = Join-Path $logs 'tunnel-url.txt'
$watchLog = Join-Path $logs 'tunnel-watch.log'
if (-not (Test-Path -LiteralPath $executable)) { throw 'cloudflared 未安装在预期位置。' }

$knownPids = @()
$lastAddress = $null
$ownsLogs = $false
Add-Content -LiteralPath $watchLog -Value "$(Get-Date -Format o) Watcher started configured_protocol=$protocol target=$target"
while ($true) {
    $running = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" |
        Where-Object { $_.ExecutablePath -eq $executable -and $_.CommandLine -match '--url\s+"?http://127\.0\.0\.1:8000(?:"|\s|$)' }
    $currentPids = @($running | ForEach-Object { $_.ProcessId })
    foreach ($previousPid in $knownPids) {
        if ($previousPid -notin $currentPids) {
            Add-Content -LiteralPath $watchLog -Value "$(Get-Date -Format o) Tunnel process disappeared PID=$previousPid"
        }
    }
    foreach ($process in $running) {
        if ($process.ProcessId -notin $knownPids) {
            $observedProtocol = 'auto/unspecified'
            if ($process.CommandLine -match '--protocol[=\s]+"?([a-z0-9]+)') { $observedProtocol = $Matches[1] }
            Add-Content -LiteralPath $watchLog -Value "$(Get-Date -Format o) Observed tunnel PID=$($process.ProcessId) requested_protocol=$observedProtocol; connection status not verified"
        }
    }
    $knownPids = $currentPids
    if (-not $running) {
        # 临时隧道重启后地址会变化，旧地址不可继续使用。
        [System.IO.File]::WriteAllText($urlFile, '隧道正在重新连接，新地址生成后会更新。')
        $child = Start-Process -FilePath $executable -ArgumentList 'tunnel','--protocol',$protocol,'--url',$target -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
        Add-Content -LiteralPath $watchLog -Value "$(Get-Date -Format o) Started tunnel PID=$($child.Id) configured_protocol=$protocol; awaiting connection (see tunnel-stderr.log)"
        $knownPids = @($child.Id)
        $lastAddress = $null
        $ownsLogs = $true
    }
    if ($ownsLogs -and (Test-Path -LiteralPath $stderrLog)) {
        $address = Select-String -LiteralPath $stderrLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' |
            Select-Object -Last 1
        if ($address -and $address.Matches[0].Value -ne $lastAddress) {
            $lastAddress = $address.Matches[0].Value
            [System.IO.File]::WriteAllText($urlFile, $lastAddress)
            Add-Content -LiteralPath $watchLog -Value "$(Get-Date -Format o) Public URL updated url=$lastAddress configured_protocol=$protocol; URL issued, connection status in tunnel-stderr.log"
        }
    }
    Start-Sleep -Seconds 10
}
