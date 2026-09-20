$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = if ($env:QAGENT_WORKBENCH_CONFIG) { $env:QAGENT_WORKBENCH_CONFIG } else { Join-Path $repoRoot 'config/workbench.yaml' }
$pythonBinary = if ($env:PYTHON_BINARY) { $env:PYTHON_BINARY } else { 'python' }

if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { throw "QAGENT_WORKBENCH_CONFIG does not point to a file: $configPath" }
$arguments = @('-X', 'utf8', (Join-Path $repoRoot 'app/workbench.py'), '--config', $configPath)
if ($env:QAGENT_PORT) {
    $portNumber = 0
    if (-not [int]::TryParse($env:QAGENT_PORT, [ref]$portNumber) -or $portNumber -lt 1 -or $portNumber -gt 65535) { throw 'QAGENT_PORT must be between 1 and 65535' }
    $arguments += @('--port', $portNumber)
}
if ($env:QAGENT_RAW_FILE) {
    if (-not (Test-Path -LiteralPath $env:QAGENT_RAW_FILE -PathType Leaf)) { throw 'QAGENT_RAW_FILE does not point to a file' }
    $arguments += @('--raw-file', $env:QAGENT_RAW_FILE)
}
if ($env:QAGENT_LLM_OVERLAY) {
    if (-not (Test-Path -LiteralPath $env:QAGENT_LLM_OVERLAY -PathType Leaf)) { throw 'QAGENT_LLM_OVERLAY does not point to a file' }
    $arguments += @('--agent-overlay', $env:QAGENT_LLM_OVERLAY)
}

& $pythonBinary @arguments
exit $LASTEXITCODE
