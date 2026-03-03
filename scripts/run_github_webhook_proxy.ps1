param(
    [Parameter(Mandatory = $false)]
    [string]$ChannelUrl = "",

    [Parameter(Mandatory = $false)]
    [string]$TargetUrl = "http://localhost:8080/api/indexer/webhooks/github"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ChannelUrl)) {
    Write-Host "Missing -ChannelUrl."
    Write-Host ""
    Write-Host "1) Open https://smee.io/new"
    Write-Host "2) Copy the generated channel URL (https://smee.io/<id>)"
    Write-Host "3) Re-run this script with -ChannelUrl"
    exit 1
}

Write-Host "Starting webhook forwarder..."
Write-Host "Channel: $ChannelUrl"
Write-Host "Target : $TargetUrl"
Write-Host ""
Write-Host "Set your GitHub webhook URL to:"
Write-Host "  $ChannelUrl"
Write-Host ""

& npx --yes smee-client --url $ChannelUrl --target $TargetUrl
