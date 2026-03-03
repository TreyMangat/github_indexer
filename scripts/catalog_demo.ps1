param(
  [string]$BaseUrl = "http://localhost:8080",
  [string]$ActorId = "demo-user",
  [string]$Org = "demo-org",
  [string]$ApiToken = "",
  [string]$Query = "payments"
)

function Invoke-Api {
  param(
    [string]$Method,
    [string]$Path,
    [object]$Body = $null
  )

  $headers = @{}
  if ($ApiToken -ne "") {
    $headers["Authorization"] = "Bearer $ApiToken"
    $headers["X-FF-Token"] = $ApiToken
  }

  $uri = "$BaseUrl$Path"
  if ($null -eq $Body) {
    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers
  }

  $json = $Body | ConvertTo-Json -Depth 8
  return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -ContentType "application/json" -Body $json
}

Write-Host "Seeding demo catalog data for actor=$ActorId org=$Org"
$seed = Invoke-Api -Method POST -Path "/api/indexer/catalog/dev/seed" -Body @{
  actor_id = $ActorId
  org = $Org
}
$seed | ConvertTo-Json -Depth 8

Write-Host "Running catalog suggest query='$Query'"
$suggest = Invoke-Api -Method POST -Path "/api/indexer/catalog/suggest" -Body @{
  actor_id = $ActorId
  org = $Org
  query = $Query
  top_k_repos = 5
  top_k_branches_per_repo = 5
}
$suggest | ConvertTo-Json -Depth 12
