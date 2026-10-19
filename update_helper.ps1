# Local updater hand-off. This script receives paths as JSON, not command text.
$ErrorActionPreference = 'Stop'
$plan = Get-Content -LiteralPath $env:PADDLEOCR_UPDATE_PLAN -Raw -Encoding UTF8 | ConvertFrom-Json
$env:PADDLEOCR_UPDATE_PLAN = $null
$moved = $false
$newProcess = $null
$workingDirectory = Split-Path -Parent $plan.target
if (Test-Path -LiteralPath $plan.cwd -PathType Container) { $workingDirectory = $plan.cwd }

function Write-Log([string]$message) {
    try { Add-Content -LiteralPath $plan.log -Value ((Get-Date -Format o) + ' ' + $message) -Encoding UTF8 } catch { }
}

function Write-Result([string]$status, [string]$message, [bool]$restored) {
    $record = @{ status = $status; version = $plan.version; previous_version = $plan.previous_version;
        message = $message; restored = $restored; log = $plan.log; backup = $plan.backup }
    $temporary = $plan.result + '.tmp'
    try {
        $record | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $plan.result -Force
    } catch { Write-Log 'Could not save the update result.' }
}

function Retry-FileOperation([scriptblock]$operation) {
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try { & $operation; return } catch {
            if ($attempt -eq 59) { throw }
            Start-Sleep -Milliseconds 500
        }
    }
}

function Get-SHA256([string]$path) {
    # Do not depend on Get-FileHash/module autoloading in the inherited host.
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = [System.IO.File]::OpenRead($path)
        return [System.BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        if ($null -ne $stream) { $stream.Dispose() }
        $algorithm.Dispose()
    }
}

function Check-File([string]$path) {
    if ((Get-Item -LiteralPath $path).Length -ne [long]$plan.size) { throw 'Update size mismatch.' }
    if ((Get-SHA256 $path) -ne $plan.sha256) {
        throw 'Update SHA-256 mismatch.'
    }
}

$mutex = New-Object System.Threading.Mutex($false, 'Local\PaddleOCRLocalUpdate')
try { $ownsMutex = $mutex.WaitOne(0) }
catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
if (-not $ownsMutex) {
    Write-Log 'Another update is already in progress.'
    $mutex.Dispose()
    exit 2
}

try {
    [System.IO.File]::WriteAllText($plan.handshake, 'ready')
    Write-Log 'Waiting for the current application to exit.'
    $oldProcess = Get-Process -Id $plan.pid -ErrorAction SilentlyContinue
    if ($null -ne $oldProcess) { Wait-Process -Id $plan.pid -Timeout 120 }
    if ($plan.kind -eq 'source') {
        foreach ($property in $plan.source_record.files.PSObject.Properties) {
            $path = Join-Path $plan.source_record.directory $property.Name
            if ((Get-SHA256 $path) -ne $property.Value) {
                throw 'Source file changed before installation.'
            }
        }
        $record = $plan.source_record | ConvertTo-Json -Depth 6
        [System.IO.File]::WriteAllText($plan.active + '.tmp', $record, (New-Object System.Text.UTF8Encoding($false)))
        if (Test-Path -LiteralPath $plan.active) {
            # Windows PowerShell 5.1 can bind $null to an empty .NET string,
            # which File.Replace rejects as an invalid backup path. A real
            # backup also keeps replacement and rollback state atomic.
            Write-Log ('Replacing source activation record: ' + $plan.active + '; backup: ' + $plan.source_backup)
            [System.IO.File]::Replace($plan.active + '.tmp', $plan.active, $plan.source_backup)
        } else {
            [System.IO.File]::Move($plan.active + '.tmp', $plan.active)
        }
        $moved = $true
    } else {
        Check-File $plan.payload
        [System.IO.File]::Copy($plan.payload, $plan.ready, $false)
        Check-File $plan.ready
        Retry-FileOperation { [System.IO.File]::Move($plan.target, $plan.backup) }
        $moved = $true
        [System.IO.File]::Move($plan.ready, $plan.target)
    }
    Write-Log 'New program installed; waiting for its startup acknowledgement.'
    $env:PADDLEOCR_UPDATE_HEALTH = $plan.health
    $newProcess = Start-Process -FilePath $plan.target -WorkingDirectory $workingDirectory -PassThru
    $deadline = (Get-Date).AddSeconds([int]$plan.health_timeout)
    $healthy = $false
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $plan.health) {
            $version = (Get-Content -LiteralPath $plan.health -Raw -Encoding UTF8).Trim()
            if ($version -eq $plan.version) { $healthy = $true; break }
            throw 'New program acknowledged an unexpected version.'
        }
        $newProcess.Refresh()
        if ($newProcess.HasExited) { throw 'New program exited before startup acknowledgement.' }
        Start-Sleep -Milliseconds 250
    }
    if (-not $healthy) { throw 'New program did not acknowledge startup in time.' }
    Write-Result 'installed' 'The updated program started successfully.' $false
    Write-Log 'Update complete. Previous program retained as a backup.'
    if ($plan.kind -ne 'source') { Remove-Item -LiteralPath $plan.payload -ErrorAction SilentlyContinue }
} catch {
    $failure = $_.Exception.Message
    Write-Log ('Update failed: ' + $failure)
    Write-Log ($_.Exception.ToString())
    if ($_.ScriptStackTrace) { Write-Log $_.ScriptStackTrace }
    $restored = $false
    $restart = $null
    try {
        if ($null -ne $newProcess) {
            $newProcess.Refresh()
            if (-not $newProcess.HasExited) {
                & "$env:SystemRoot\System32\taskkill.exe" /PID $newProcess.Id /T /F *> $null
            }
        }
        if ($moved) {
            if ($plan.kind -eq 'source') {
                if (Test-Path -LiteralPath $plan.source_backup) {
                    Copy-Item -LiteralPath $plan.source_backup -Destination $plan.active -Force
                } else {
                    Remove-Item -LiteralPath $plan.active -ErrorAction SilentlyContinue
                }
            } else {
                Retry-FileOperation {
                    if (Test-Path -LiteralPath $plan.target) { [System.IO.File]::Delete($plan.target) }
                    [System.IO.File]::Move($plan.backup, $plan.target)
                }
            }
            $restored = $true
            $restart = $plan.target
        } elseif ($null -eq (Get-Process -Id $plan.pid -ErrorAction SilentlyContinue)) {
            $restart = $plan.target
        }
    } catch {
        Write-Log ('Restoration failed: ' + $_.Exception.Message)
        if ($plan.kind -eq 'source') { $restart = $plan.target }
        elseif (Test-Path -LiteralPath $plan.backup) { $restart = $plan.backup }
    }
    Write-Result 'failed' $failure $restored
    $env:PADDLEOCR_UPDATE_HEALTH = $null
    if ($null -ne $restart) {
        try { Start-Process -FilePath $restart -WorkingDirectory $workingDirectory }
        catch { Write-Log ('Could not restart the previous program: ' + $_.Exception.Message) }
    }
} finally {
    if (Test-Path -LiteralPath $plan.ready) { Remove-Item -LiteralPath $plan.ready -ErrorAction SilentlyContinue }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
