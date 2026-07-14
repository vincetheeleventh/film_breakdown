$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$hostName = "127.0.0.1"
$port = 8765
$url = "http://$hostName`:$port/"
$appWindowArgs = @("--app=$url", "--class=FilmStudyTool")

function Get-BravePath {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "BraveSoftware\Brave-Browser\Application\brave.exe"),
        (Join-Path $env:ProgramFiles "BraveSoftware\Brave-Browser\Application\brave.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "BraveSoftware\Brave-Browser\Application\brave.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $command = Get-Command brave.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return $null
}

function Test-FilmStudyServer {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-FilmStudyServer)) {
    $python = Get-Command python -ErrorAction Stop
    Start-Process `
        -FilePath $python.Source `
        -ArgumentList @("-m", "film_study_tool.ui_server", "--host", $hostName, "--port", [string]$port) `
        -WorkingDirectory $root `
        -WindowStyle Minimized

    $deadline = (Get-Date).AddSeconds(12)
    while ((Get-Date) -lt $deadline) {
        if (Test-FilmStudyServer) { break }
        Start-Sleep -Milliseconds 300
    }
}

$brave = Get-BravePath
if ($brave) {
    Start-Process -FilePath $brave -ArgumentList $appWindowArgs
} else {
    Start-Process $url
}
