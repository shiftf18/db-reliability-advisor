$ErrorActionPreference = "Stop"

function Check {
    param(
        [string]$Name,
        [string]$Url
    )

    $maxAttempts = 20

    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            Invoke-WebRequest `
                -Uri $Url `
                -UseBasicParsing `
                -TimeoutSec 30 `
                -MaximumRedirection 0 `
                | Out-Null

            Write-Host "ok: $Name"
            return
        }
        catch {
            if ($attempt -eq $maxAttempts) {
                throw
            }

            Start-Sleep -Seconds 2
        }
    }
}

# MongoDB
docker compose exec -T mongo mongosh `
    --quiet `
    --username root `
    --password local_root_password `
    --authenticationDatabase admin `
    --eval "quit(db.adminCommand({ping: 1}).ok ? 0 : 2)" `
    localhost:27017/admin | Out-Null

if ($LASTEXITCODE -ne 0) {
    throw "MongoDB health check failed"
}

Write-Host "ok: MongoDB"

Check "MongoDB exporter" "http://localhost:9216/metrics"
Check "Prometheus" "http://localhost:9090/-/ready"
Check "Loki" "http://localhost:3100/ready"
Check "Grafana" "http://localhost:3001/api/health"
Check "Alertmanager" "http://localhost:9093/-/ready"
Check "Analysis Service" "http://localhost:8000/health"
Check "Orders API" "http://localhost:8001/health"
Check "Report index" "http://localhost:8000/"

# Mock Contract C response
$report = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/api/v1/dev/mock/query-regression"

$reportJson = $report | ConvertTo-Json -Depth 20

if ($report.schemaVersion -ne "1.0") {
    throw "Unexpected schemaVersion"
}

if ($reportJson -notmatch "Query Efficiency Regression") {
    throw "Expected report title not found"
}

Write-Host "ok: mock Contract C response"

$analysisId = $report.analysisId

Check "Rendered report" "http://localhost:8000/analyses/$analysisId/report"