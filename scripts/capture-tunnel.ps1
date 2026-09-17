$runtime = 'D:\RugScene-Match-main\runtime-logs'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$stdout = Join-Path $runtime 'tunnel-stdout.log'
$stderr = Join-Path $runtime 'tunnel-stderr.log'
$proc = Start-Process -FilePath 'C:\Program Files (x86)\cloudflared\cloudflared.exe' -ArgumentList 'tunnel','--url','http://127.0.0.1:8000' -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  $match = Select-String -LiteralPath $stdout,$stderr -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -Last 1
  if ($match) { $match.Matches[0].Value | Set-Content (Join-Path $runtime 'tunnel-url.txt'); Write-Output $match.Matches[0].Value; exit 0 }
}
Get-Content $stdout,$stderr -ErrorAction SilentlyContinue
exit 1
