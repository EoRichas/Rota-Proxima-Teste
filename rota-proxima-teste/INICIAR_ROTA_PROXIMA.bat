@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal EnableExtensions EnableDelayedExpansion

echo ==========================================
echo       ROTA PROXIMA - PRODUCAO SP
echo ==========================================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo Python nao foi encontrado neste computador.
  echo Instale Python 3 e marque a opcao "Add Python to PATH".
  pause
  exit /b 1
)

python -c "import requests" >nul 2>nul
if errorlevel 1 (
  echo Preparando dependencia necessaria...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Nao foi possivel instalar as dependencias.
    pause
    exit /b 1
  )
)

echo Encerrando instancias antigas do Rota Proxima...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -match 'server\.py' }; foreach($p in $procs){ try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Host ('  Encerrado PID ' + $p.ProcessId) } catch {} }"
timeout /t 2 /nobreak >nul

set "PORTPID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8080 .*LISTENING"') do set "PORTPID=%%P"
if defined PORTPID (
  echo.
  echo ERRO: a porta 8080 ainda esta ocupada pelo PID !PORTPID!.
  echo O Rota Proxima NAO sera iniciado para evitar duas versoes ao mesmo tempo.
  echo.
  tasklist /FI "PID eq !PORTPID!"
  echo.
  echo Feche esse processo ou reinicie o computador e tente novamente.
  echo Voce tambem pode executar DIAGNOSTICO_REDE.bat para ver os detalhes.
  echo.
  pause
  exit /b 1
)

echo.
echo Acesse no computador:
echo   http://localhost:8080

echo.
echo Enderecos possiveis para celular na MESMA rede Wi-Fi:
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ips = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.|26\.)' -and ($_.IPAddress -match '^192\.168\.' -or $_.IPAddress -match '^10\.' -or $_.IPAddress -match '^172\.(1[6-9]|2[0-9]|3[0-1])\.') -and $_.InterfaceAlias -notmatch 'vEthernet|Virtual|VPN|Radmin|Hamachi|Tailscale|WSL|Loopback|Hyper-V|VMware|VirtualBox' }; if(-not $ips){ Write-Host '  Nenhum IPv4 local encontrado automaticamente.' -ForegroundColor Yellow } else { $ips | ForEach-Object { Write-Host ('  http://' + $_.IPAddress + ':8080   [' + $_.InterfaceAlias + ']') } }"

echo.
echo NAO use endereco 26.x.x.x, a menos que o celular esteja conectado ao mesmo VPN.
echo Se o celular nao abrir, execute uma vez COMO ADMINISTRADOR: LIBERAR_ACESSO_CELULAR.bat
echo.
echo IMPORTANTE: no terminal deve aparecer:
echo ROTA PROXIMA - BUILD SP-GOLIVE-NETWORKFIX2-2026-08-12
echo Escutando na rede: 0.0.0.0:8080 (IPv4)
echo.
echo Para encerrar, pressione CTRL+C.
echo.
python "%~dp0server.py"
pause
