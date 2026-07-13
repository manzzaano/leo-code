# Corrida-señal única OC vs OCMCP (para medir un cambio antes de la validación 3×).
# Uso: pwsh -NoProfile -File benchmark\run_signal.ps1 <etiqueta>
param([string]$label = "signal")
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\Ismael\Desktop\_Sandbox\leo-code"
$env:PYTHONIOENCODING = "utf-8"
$res = "benchmark\results_real"
$head = (git rev-parse --short HEAD)
Add-Content "$res\validation_progress.log" "=== RUN $label start $(Get-Date -Format HH:mm:ss) (HEAD=$head) ==="
python -u benchmark\run_real.py --systems oc,ocmcp --batch 1 --isolate *> "$res\$label.log"
Add-Content "$res\validation_progress.log" "=== RUN $label exit=$LASTEXITCODE $(Get-Date -Format HH:mm:ss) ==="
if ($LASTEXITCODE -eq 0) {
    Copy-Item "$res\summary.json" "$res\$label.json" -Force
}
