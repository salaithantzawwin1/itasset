# Start the portable embedded Postgres OUTSIDE the orchestrator's process tree
# (WMI-created processes are not children of this shell, so they survive the
# command's cleanup and don't inherit its job object — the 0xC0000142 backend
# crashes happen when postmaster backends inherit a dying job).
$pgHome = Join-Path $env:LOCALAPPDATA 'itasset-pg'
$pg = Join-Path $pgHome 'pg\bin\pg_ctl.exe'
$data = Join-Path $pgHome 'data'
$log = Join-Path $pgHome 'pg3.log'

$cmd = "`"$pg`" -D `"$data`" -l `"$log`" -w -t 60 start"
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd }
"ReturnValue=$($r.ReturnValue) ProcessId=$($r.ProcessId)"
Start-Sleep -Seconds 3
Get-Content $log -Tail 4 -ErrorAction SilentlyContinue
