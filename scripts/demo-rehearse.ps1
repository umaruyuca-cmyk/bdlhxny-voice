# §8 seven-step automated rehearsal (gate mapping; live UI + recording still manual)
# Usage: .\scripts\demo-rehearse.ps1 [-Passes 3]

param(
  [int]$Passes = 3
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$results = New-Object System.Collections.Generic.List[object]

function Invoke-Step {
  param(
    [string]$Name,
    [scriptblock]$Action
  )
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $ok = $true
  $err = ""
  try {
    & $Action | Out-Null
  } catch {
    $ok = $false
    $err = $_.Exception.Message
  }
  $sw.Stop()
  # Explicit Write-Output so callers using List.Add get exactly one object.
  Write-Output ([pscustomobject]@{
      name  = $Name
      ok    = $ok
      ms    = $sw.ElapsedMilliseconds
      error = $err
    })
}

for ($i = 1; $i -le $Passes; $i++) {
  Write-Host ""
  Write-Host "===== rehearsal pass $i / $Passes ====="
  $passStart = Get-Date
  $steps = New-Object System.Collections.Generic.List[object]

  [void]$steps.Add((Invoke-Step "1-dashboard-contract" {
    Push-Location (Join-Path $root "sentinel-console")
    try {
      cmd /c "npm test --silent >nul 2>&1"
      if ($LASTEXITCODE -ne 0) { throw "npm test exit $LASTEXITCODE" }
    } finally { Pop-Location }
  }))

  [void]$steps.Add((Invoke-Step "2-demo-inject-contract" {
    Push-Location (Join-Path $root "sentinel-engine")
    try {
      cmd /c "uv run python -m pytest -q tests/api/test_demo_events.py >nul 2>&1"
      if ($LASTEXITCODE -ne 0) { throw "pytest demo_events exit $LASTEXITCODE" }
    } finally { Pop-Location }
  }))

  [void]$steps.Add((Invoke-Step "3-wakeup-notify" {
    Push-Location (Join-Path $root "sentinel-engine")
    try {
      cmd /c "uv run python -m pytest -q tests/watch/test_wakeup_flow.py >nul 2>&1"
      if ($LASTEXITCODE -ne 0) { throw "pytest wakeup exit $LASTEXITCODE" }
    } finally { Pop-Location }
  }))

  [void]$steps.Add((Invoke-Step "4-5-sse-blocks" {
    Push-Location (Join-Path $root "sentinel-engine")
    try {
      cmd /c "uv run python -m pytest -q tests/api/test_sse_v2.py tests/api/test_chat_result_v2.py >nul 2>&1"
      if ($LASTEXITCODE -ne 0) { throw "pytest sse/blocks exit $LASTEXITCODE" }
    } finally { Pop-Location }
  }))

  [void]$steps.Add((Invoke-Step "6-pause-resume" {
    Push-Location (Join-Path $root "sentinel-engine")
    try {
      cmd /c "uv run python -m pytest -q tests/engine/test_checkpoint.py >nul 2>&1"
      if ($LASTEXITCODE -ne 0) { throw "pytest checkpoint exit $LASTEXITCODE" }
    } finally { Pop-Location }
  }))

  [void]$steps.Add((Invoke-Step "7-c1-c2" {
    Push-Location (Join-Path $root "sentinel-engine")
    try {
      cmd /c "uv run python -m pytest -q tests/engine/test_suitability.py tests/guardrails/test_guardrail_policies.py >nul 2>&1"
      if ($LASTEXITCODE -ne 0) { throw "pytest C-1/C-2 exit $LASTEXITCODE" }
    } finally { Pop-Location }
  }))

  $failed = @($steps | Where-Object { $_.ok -ne $true })
  $elapsed = [math]::Round(((Get-Date) - $passStart).TotalSeconds, 1)
  [void]$results.Add([pscustomobject]@{
      pass     = $i
      ok       = ($failed.Count -eq 0)
      seconds  = $elapsed
      failures = ($failed | ForEach-Object { $_.name }) -join ","
    })

  foreach ($s in $steps) {
    Write-Host ("  {0,-24} ok={1,-5} {2,5}ms  {3}" -f $s.name, $s.ok, $s.ms, $s.error)
  }
  if ($failed.Count -gt 0) {
    Write-Host ("pass {0} FAILED" -f $i)
  } else {
    Write-Host ("pass {0} OK in {1}s" -f $i, $elapsed)
  }
}

Write-Host ""
Write-Host "===== summary ====="
foreach ($r in $results) {
  Write-Host ("  pass={0} ok={1} seconds={2} failures={3}" -f $r.pass, $r.ok, $r.seconds, $r.failures)
}
$bad = @($results | Where-Object { $_.ok -ne $true })
if ($bad.Count -gt 0) {
  Write-Error "rehearsal not all green"
  exit 1
}
Write-Host ("automated rehearsal {0} passes OK. Live browser + recordings/ still manual." -f $Passes)
