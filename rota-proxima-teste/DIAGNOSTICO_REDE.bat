@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal EnableExtensions

echo ==========================================
echo      DIAGNOSTICO ROTA PROXIMA
echo ==========================================
echo.
echo [1] Servidor na porta 8080:
netstat -ano | findstr /R /C:":8080 .*LISTENING"
echo.
echo [2] Teste local:
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8080/api/health' -TimeoutSec 3; $r | ConvertTo-Json -Compress } catch { Write-Host ('FALHOU: ' + $_.Exception.Message) -ForegroundColor Red }"
echo.
echo [3] IPv4 locais recomendados:
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ips = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.|26\.)' -and ($_.IPAddress -match '^192\.168\.' -or $_.IPAddress -match '^10\.' -or $_.IPAddress -match '^172\.(1[6-9]|2[0-9]|3[0-1])\.') -and $_.InterfaceAlias -notmatch 'vEthernet|Virtual|VPN|Radmin|Hamachi|Tailscale|WSL|Loopback|Hyper-V|VMware|VirtualBox' }; if($ips){ $ips | Select-Object InterfaceAlias,IPAddress | Format-Table -AutoSize } else { Write-Host 'Nenhum IPv4 privado recomendado encontrado.' -ForegroundColor Yellow }"
echo.
echo [4] Regra do Firewall:
netsh advfirewall firewall show rule name="Rota Proxima - Rede Local 8080"
echo.
echo [5] Processos que ocupam a porta 8080:
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8080 .*LISTENING"') do (
  echo --- PID %%P ---
  tasklist /FI "PID eq %%P"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=%%P' -ErrorAction SilentlyContinue; if($p){ Write-Host ('Comando: ' + $p.CommandLine) }"
)
echo.
echo Se aparecer MAIS DE UM PID em 0.0.0.0:8080, feche todos os servidores
echo Rota Proxima e execute novamente INICIAR_ROTA_PROXIMA.bat.
echo.
pause
