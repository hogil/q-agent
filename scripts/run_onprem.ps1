$ErrorActionPreference = 'Stop'
$python = if ($env:QAGENT_PYTHON) { $env:QAGENT_PYTHON } else { 'python' }
$entry = Join-Path $PSScriptRoot '../app/run_agent.py'

& $python -X utf8 $entry @args
exit $LASTEXITCODE
