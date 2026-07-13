# Corre N corridas pareadas OC vs OCMCP y guarda cada summary como harness_runN.json.
# Desatado del harness de Claude: lanzar con Start-Process. Marker: harness_ALL_DONE.txt
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\Ismael\Desktop\_Sandbox\leo-code"
$env:PYTHONIOENCODING = "utf-8"
$res = "benchmark\results_real"
Remove-Item "$res\harness_ALL_DONE.txt" -ErrorAction SilentlyContinue
foreach ($i in 1..3) {
    "=== RUN $i start $(Get-Date -Format HH:mm:ss) ===" | Add-Content "$res\validation_progress.log"
    python -u benchmark\run_real.py --systems oc,ocmcp --batch 1 --isolate *> "$res\harness_run$i.log"
    "=== RUN $i exit=$LASTEXITCODE $(Get-Date -Format HH:mm:ss) ===" | Add-Content "$res\validation_progress.log"
    if ($LASTEXITCODE -eq 0) {
        Copy-Item "$res\summary.json" "$res\harness_run$i.json" -Force
    }
}
"ALL_RUNS_DONE $(Get-Date -Format HH:mm:ss)" | Add-Content "$res\validation_progress.log"
"done" | Set-Content "$res\harness_ALL_DONE.txt"
