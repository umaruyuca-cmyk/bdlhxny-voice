# Sentinel demo event inject (design §8 step #2, C-4)
# Configurable symbol / magnitude. Default: 300750 @ -5.2%.
#
# Usage:
#   . .\scripts\load-deploy-env.ps1   # optional
#   .\scripts\demo-inject.ps1
#   .\scripts\demo-inject.ps1 -Symbol 600519 -Pct -3.5
#   .\scripts\demo-inject.ps1 -BaseUrl http://127.0.0.1:8090 -Symbol 300750 -Pct -5.2
#
# Requires orchestrator with BDLH_DEMO_MODE=true (else 404).

param(
  [string]$BaseUrl = $(if ($env:BDLH_DEMO_BASE_URL) { $env:BDLH_DEMO_BASE_URL } else { "http://127.0.0.1:8090" }),
  [string]$Symbol = $(if ($env:BDLH_DEMO_SYMBOL) { $env:BDLH_DEMO_SYMBOL } else { "300750" }),
  [double]$Pct = $(if ($env:BDLH_DEMO_PCT) { [double]$env:BDLH_DEMO_PCT } else { -5.2 }),
  [string]$Type = "price_threshold",
  [string]$Direction = ""
)

$ErrorActionPreference = "Stop"
$uri = ($BaseUrl.TrimEnd("/")) + "/api/v1/internal/demo/events"
$body = @{
  type   = $Type
  symbol = $Symbol
  pct    = $Pct
}
if ($Direction) { $body.direction = $Direction }

$json = $body | ConvertTo-Json -Compress
Write-Host "POST $uri"
Write-Host "body $json"

try {
  $resp = Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json; charset=utf-8" -Body $json
} catch {
  Write-Error ("inject failed: {0}. Ensure orchestrator is up with BDLH_DEMO_MODE=true." -f $_.Exception.Message)
  exit 1
}

Write-Host ("ok event_id={0} source={1} dedupe_key={2}" -f $resp.event_id, $resp.source, $resp.dedupe_key)
if ($resp.source -ne "demo_inject") {
  Write-Error ("C-4 failed: source must be demo_inject, got {0}" -f $resp.source)
  exit 1
}
