# Prueba la conexión a Elastic Cloud y guarda la URL con credenciales en el secreto
# pocket-price-es (Cloud Run la inyecta como ES_URL). No muestra la clave en pantalla.
# Uso (desde la raíz del proyecto):
#   powershell -ExecutionPolicy Bypass -File infra\gcp\cargar_es.ps1 -Proyecto <id-de-tu-proyecto-gcp>

param([Parameter(Mandatory = $true)][string]$Proyecto)

$ErrorActionPreference = "Stop"
$gcloud = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
$proyecto = $Proyecto
$secreto = "pocket-price-es"

$env_ = @{}
foreach ($linea in Get-Content .env) {
    if ($linea -match '^\s*(ES_CLOUD_ENDPOINT|ES_CLOUD_PASSWORD)\s*=\s*(.*)$') { $env_[$Matches[1]] = $Matches[2].Trim() }
}
$endpoint = $env_["ES_CLOUD_ENDPOINT"].TrimEnd("/")
$clave = $env_["ES_CLOUD_PASSWORD"]

# 1. Probar la conexión (solo muestra nombre del clúster y versión)
$auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("elastic:$clave"))
$info = Invoke-RestMethod -Uri $endpoint -Headers @{ Authorization = "Basic $auth" }
Write-Host "[ok] Conexion a Elastic: cluster $($info.cluster_name), version $($info.version.number)"

# 2. Crear el secreto si no existe y agregar la URL como nueva versión
# (secrets list no falla si no existe; describe sí, y con "Stop" PowerShell 5.1 corta el script)
$existe = & $gcloud secrets list --project=$proyecto --filter="name~/$secreto`$" --format="value(name)"
if (-not $existe) {
    & $gcloud secrets create $secreto --project=$proyecto --replication-policy=automatic
}
$url = $endpoint -replace '^https://', "https://elastic:$clave@"
$tmp = [IO.Path]::GetTempFileName()
try {
    [IO.File]::WriteAllText($tmp, $url, (New-Object Text.UTF8Encoding $false))
    & $gcloud secrets versions add $secreto --project=$proyecto --data-file=$tmp
} finally {
    Remove-Item $tmp -Force
}
