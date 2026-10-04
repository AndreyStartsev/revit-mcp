param([string]$State = 'true')
$ErrorActionPreference = 'SilentlyContinue'
$isBusy = ($State.ToLower() -eq 'true' -or $State -eq '1')
try {
    $dir = Join-Path $env:USERPROFILE '.revit_mcp\instances'
    if (Test-Path $dir) {
        $files = Get-ChildItem $dir -Filter "*.json"
        foreach ($f in $files) {
            $data = Get-Content $f.FullName | ConvertFrom-Json
            if ($data.port -and $data.auth_token) {
                $headers = @{
                    'Authorization' = "Bearer $($data.auth_token)"
                    'Content-Type' = 'application/json'
                }
                $body = @{ busy = $isBusy } | ConvertTo-Json
                $null = Invoke-RestMethod -Uri "http://127.0.0.1:$($data.port)/api/set_busy" -Method POST -Headers $headers -Body $body -TimeoutSec 1
            }
        }
    }
} catch {
}
Write-Output '{}'
