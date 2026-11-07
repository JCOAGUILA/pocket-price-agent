# Carga las claves de los LLM del .env al secreto pocket-price-llm (Secret Manager).
# Lo corre la persona dueña de las claves: no muestra ningún valor en pantalla.
# Uso (desde la raíz del proyecto):
#   powershell -ExecutionPolicy Bypass -File infra\gcp\cargar_secretos.ps1 -Proyecto <id-de-tu-proyecto-gcp>

param([Parameter(Mandatory = $true)][string]$Proyecto)

$ErrorActionPreference = "Stop"
$gcloud = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
$claves = "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LANGSMITH_API_KEY"

$valores = [ordered]@{}
foreach ($linea in Get-Content .env) {
    if ($linea -match '^\s*([A-Z_]+)\s*=\s*(.*)$' -and $claves -contains $Matches[1]) {
        $valores[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
    }
}
foreach ($c in $claves) {
    if ($valores[$c]) { Write-Host "[ok]    $c presente" } else { Write-Host "[falta] $c vacia o ausente" }
}

# Archivo temporal sin BOM: Secret Manager guarda los bytes tal cual y la app hace json.loads.
$tmp = [IO.Path]::GetTempFileName()
try {
    [IO.File]::WriteAllText($tmp, ($valores | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
    & $gcloud secrets versions add pocket-price-llm --project=$Proyecto --data-file=$tmp
} finally {
    Remove-Item $tmp -Force
}
