<#
.SYNOPSIS
    Starts all three Curriculum Portal services (nlp-engine, backend, frontend)
    in one command, in dependency order, with readiness checks between them.

.DESCRIPTION
    Services are started in the order backend work actually depends on:

        nlp-engine (:8000) -> backend (:4000) -> frontend (:5173)

    Each is started only once the previous one reports healthy, so you never
    get a frontend that loads against a backend that can't analyze anything.
    All three run as children of this script and share its console — press
    Ctrl+C once and every service is stopped.

    Postgres is NOT started here: it's usually a system service or a Docker
    container with its own lifecycle. The nlp-engine's readiness check covers
    whether the database is actually reachable and seeded — see RUN.md step 1.

.PARAMETER Install
    Do first-time setup before starting: create the Python venv, install
    requirements, download the spaCy model, and npm install both Node apps.
    Run this once; afterwards plain .\start-all.ps1 is enough.

.PARAMETER NoHealthWait
    Start all three back-to-back without waiting for readiness. Faster, but
    early requests may fail while the NLP models are still loading.

.PARAMETER ReadyTimeoutSeconds
    How long to wait for the nlp-engine to become ready. The first ever run
    downloads ~100MB of models, so the default is deliberately patient.

.EXAMPLE
    .\start-all.ps1 -Install
    First run: sets everything up, then starts all three services.

.EXAMPLE
    .\start-all.ps1
    Every run after that.
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$NoHealthWait,
    [string]$BindHost = '127.0.0.1',
    [int]$NlpPort = 8000,
    [int]$BackendPort = 4000,
    [int]$FrontendPort = 5173,
    [int]$ReadyTimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'

$Root = $PSScriptRoot
$NlpDir = Join-Path $Root 'nlp-engine'
$BackendDir = Join-Path $Root 'backend'
$FrontendDir = Join-Path $Root 'frontend'
$VenvPython = Join-Path $NlpDir 'venv\Scripts\python.exe'

# Every process this script starts, so the finally block can clean them all up.
$script:Started = @()

function Write-Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }
function Write-Ok($message) { Write-Host "    $message" -ForegroundColor Green }
function Write-Warn($message) { Write-Host "    $message" -ForegroundColor Yellow }
function Write-Err($message) { Write-Host "    $message" -ForegroundColor Red }

function Test-Command($name) {
    try { $null = Get-Command $name -ErrorAction Stop; return $true } catch { return $false }
}

function Test-PortInUse($portNumber) {
    # A quick TCP connect beats Test-NetConnection here: same answer, no
    # multi-second timeout when nothing is listening.
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect('127.0.0.1', $portNumber, $null, $null)
        if ($result.AsyncWaitHandle.WaitOne(300)) {
            $client.EndConnect($result)
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Initialize-EnvFile($serviceDir, $serviceName) {
    $envPath = Join-Path $serviceDir '.env'
    $examplePath = Join-Path $serviceDir '.env.example'
    if ((Test-Path $envPath) -or -not (Test-Path $examplePath)) { return }
    Copy-Item $examplePath $envPath
    Write-Warn "$serviceName had no .env - copied .env.example. Check its DATABASE_URL before relying on it."
}

function Start-PortalService($name, $workingDir, $exe, $argumentList) {
    Write-Host "    starting $name..." -ForegroundColor DarkGray
    # -NoNewWindow so all three services log into this one console.
    $proc = Start-Process -FilePath $exe -ArgumentList $argumentList `
        -WorkingDirectory $workingDir -NoNewWindow -PassThru
    $script:Started += [pscustomobject]@{ Name = $name; Process = $proc }
    return $proc
}

function Stop-AllServices {
    if ($script:Started.Count -eq 0) { return }
    Write-Host "`n==> Shutting down..." -ForegroundColor Cyan
    # Reverse order: dependents first, so nothing logs connection errors on the
    # way out. /T kills the whole tree - node --watch and uvicorn --reload both
    # supervise a child that would otherwise survive and hold its port.
    for ($i = $script:Started.Count - 1; $i -ge 0; $i--) {
        $entry = $script:Started[$i]
        if ($entry.Process -and -not $entry.Process.HasExited) {
            Write-Host "    stopping $($entry.Name)..." -ForegroundColor DarkGray
            & taskkill /PID $entry.Process.Id /T /F 2>$null | Out-Null
        }
    }
    $script:Started = @()
    Write-Ok 'All services stopped.'
}

function Get-HealthBody($healthUrl) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
        return $response.Content | ConvertFrom-Json
    } catch {
        # A 503 readiness response still carries a useful body - read it rather
        # than treating "not ready yet" as "unreachable".
        $webResponse = $_.Exception.Response
        if ($webResponse) {
            try {
                $reader = New-Object System.IO.StreamReader($webResponse.GetResponseStream())
                return $reader.ReadToEnd() | ConvertFrom-Json
            } catch { return $null }
        }
        return $null
    }
}

function Wait-ForReady($name, $healthUrl, $timeoutSeconds, $process) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    $lastNote = ''
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) {
            throw "$name exited with code $($process.ExitCode) before becoming ready. See its output above."
        }

        $body = Get-HealthBody $healthUrl
        if ($body) {
            # `ready` is absent on the plain backend liveness endpoint, where
            # any successful response already means ready.
            $isReady = $true
            if ($null -ne $body.PSObject.Properties['ready']) { $isReady = [bool]$body.ready }
            if ($isReady) { return $body }

            $note = Format-NotReadyReason $body
            if ($note -and $note -ne $lastNote) {
                Write-Host "    waiting on $name - $note" -ForegroundColor DarkGray
                $lastNote = $note
            }
        }
        Start-Sleep -Seconds 2
    }
    throw "$name did not become ready within $timeoutSeconds seconds. Check its output above, or query $healthUrl directly."
}

function Format-NotReadyReason($body) {
    if ($null -eq $body.PSObject.Properties['checks'] -or $null -eq $body.checks) { return '' }
    $reasons = @()
    foreach ($property in $body.checks.PSObject.Properties) {
        $check = $property.Value
        if ($null -eq $check.PSObject.Properties['status']) { continue }
        if ($check.status -ne 'ok') {
            $reason = "$($property.Name): $($check.status)"
            if ($check.PSObject.Properties['detail'] -and $check.detail) { $reason += " ($($check.detail))" }
            $reasons += $reason
        }
    }
    return ($reasons -join '; ')
}

function Invoke-Setup {
    Write-Step 'First-time setup'

    if (-not (Test-Path $VenvPython)) {
        Write-Host '    creating Python venv...' -ForegroundColor DarkGray
        & python -m venv (Join-Path $NlpDir 'venv')
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python virtualenv.' }
    }

    Write-Host '    installing Python requirements (this takes a few minutes)...' -ForegroundColor DarkGray
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
    & $VenvPython -m pip install -r (Join-Path $NlpDir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'pip install -r requirements.txt failed.' }

    Write-Host '    downloading the spaCy model...' -ForegroundColor DarkGray
    & $VenvPython -m spacy download en_core_web_sm
    if ($LASTEXITCODE -ne 0) { throw 'spaCy model download failed.' }

    foreach ($dir in @($BackendDir, $FrontendDir)) {
        Write-Host "    npm install in $(Split-Path $dir -Leaf)..." -ForegroundColor DarkGray
        Push-Location $dir
        try {
            & npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed in $dir." }
        } finally {
            Pop-Location
        }
    }

    Write-Ok 'Setup complete.'
}

# ---------------------------------------------------------------------------

try {
    Write-Step 'Checking prerequisites'

    foreach ($tool in @('node', 'npm', 'python')) {
        if (-not (Test-Command $tool)) { throw "'$tool' was not found on PATH. See RUN.md for prerequisites." }
    }
    Write-Ok "node $(& node -v), npm $(& npm -v), $(& python --version)"

    foreach ($pair in @(@{ Dir = $NlpDir; Name = 'nlp-engine' }, @{ Dir = $BackendDir; Name = 'backend' }, @{ Dir = $FrontendDir; Name = 'frontend' })) {
        if (-not (Test-Path $pair.Dir)) { throw "Missing directory: $($pair.Dir). Run this script from inside curriculum-portal/." }
        Initialize-EnvFile $pair.Dir $pair.Name
    }

    if ($Install) { Invoke-Setup }

    if (-not (Test-Path $VenvPython)) {
        throw "No Python venv at $VenvPython. Run '.\start-all.ps1 -Install' once to set everything up."
    }
    foreach ($dir in @($BackendDir, $FrontendDir)) {
        if (-not (Test-Path (Join-Path $dir 'node_modules'))) {
            throw "No node_modules in $dir. Run '.\start-all.ps1 -Install' once to set everything up."
        }
    }

    foreach ($portPair in @(@{ Port = $NlpPort; Name = 'nlp-engine' }, @{ Port = $BackendPort; Name = 'backend' }, @{ Port = $FrontendPort; Name = 'frontend' })) {
        if (Test-PortInUse $portPair.Port) {
            throw "Port $($portPair.Port) ($($portPair.Name)) is already in use. Stop whatever is listening on it and try again."
        }
    }
    Write-Ok "Ports $NlpPort / $BackendPort / $FrontendPort are free."

    # --- nlp-engine ---------------------------------------------------------
    Write-Step "Starting nlp-engine on http://${BindHost}:$NlpPort"
    $nlpProc = Start-PortalService 'nlp-engine' $NlpDir $VenvPython @(
        '-m', 'uvicorn', 'app.main:app', '--host', $BindHost, '--port', $NlpPort
    )

    if (-not $NoHealthWait) {
        Write-Host '    waiting for models to load and the database to answer...' -ForegroundColor DarkGray
        $nlpHealth = Wait-ForReady 'nlp-engine' "http://${BindHost}:$NlpPort/health" $ReadyTimeoutSeconds $nlpProc
        Write-Ok "nlp-engine ready (job_skills: $($nlpHealth.checks.job_skills.count), nep_competencies: $($nlpHealth.checks.nep_competencies.count))"
        if ($nlpHealth.checks.nep_competencies.status -ne 'ok') {
            Write-Warn 'nep_competencies is empty - reports will have a null NEP score. Fix: python database/seed_nep.py'
        }
    }

    # --- backend ------------------------------------------------------------
    Write-Step "Starting backend on http://localhost:$BackendPort"
    $backendProc = Start-PortalService 'backend' $BackendDir 'node' @('--watch', 'server.js')

    if (-not $NoHealthWait) {
        Wait-ForReady 'backend' "http://localhost:$BackendPort/api/health" 60 $backendProc | Out-Null
        Write-Ok 'backend ready.'
    }

    # --- frontend -----------------------------------------------------------
    Write-Step "Starting frontend on http://localhost:$FrontendPort"
    # Vite's bin script directly, not `npm run dev`: npm.cmd wraps the real
    # process in a shell, which makes it harder to stop cleanly on Ctrl+C.
    $frontendProc = Start-PortalService 'frontend' $FrontendDir 'node' @(
        'node_modules/vite/bin/vite.js', '--port', $FrontendPort, '--strictPort'
    )

    Write-Host "`n=========================================================" -ForegroundColor Green
    Write-Host ' All services running' -ForegroundColor Green
    Write-Host "   frontend    http://localhost:$FrontendPort" -ForegroundColor Green
    Write-Host "   backend     http://localhost:$BackendPort/api/health" -ForegroundColor Green
    Write-Host "   nlp-engine  http://${BindHost}:$NlpPort/health" -ForegroundColor Green
    Write-Host "   all-in-one  http://localhost:$BackendPort/api/health/full" -ForegroundColor Green
    Write-Host ' Press Ctrl+C to stop all three.' -ForegroundColor Green
    Write-Host "=========================================================`n" -ForegroundColor Green

    # Block until Ctrl+C, or until any service dies (in which case say which).
    while ($true) {
        foreach ($entry in $script:Started) {
            if ($entry.Process.HasExited) {
                Write-Err "$($entry.Name) exited with code $($entry.Process.ExitCode). Stopping the rest."
                exit 1
            }
        }
        Start-Sleep -Seconds 1
    }
} catch {
    Write-Err $_.Exception.Message
    exit 1
} finally {
    Stop-AllServices
}
