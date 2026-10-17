# Usage: ./generate_dxf.ps1 [payload.json] [output_directory]
$runtimePath = Join-Path (Split-Path -Parent $PSScriptRoot) '.dxf-runtime'
$previousPythonPath = $env:PYTHONPATH
try {
    if (Test-Path -LiteralPath $runtimePath) {
        $env:PYTHONPATH = $runtimePath + [IO.Path]::PathSeparator + $previousPythonPath
    }
    & python (Join-Path $PSScriptRoot 'json_to_dxf.py') @args
    $resultCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
exit $resultCode
