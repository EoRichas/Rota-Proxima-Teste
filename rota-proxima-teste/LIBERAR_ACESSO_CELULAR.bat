@echo off
chcp 65001 >nul
cd /d "%~dp0"

net session >nul 2>&1
if not %errorlevel%==0 (
  echo Solicitando permissao de Administrador para liberar a porta 8080...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo ==========================================
echo   LIBERAR ROTA PROXIMA NA REDE LOCAL
echo ==========================================
echo.
echo A regra abaixo permite TCP 8080 apenas para a rede/sub-rede local.
echo.
netsh advfirewall firewall delete rule name="Rota Proxima - Rede Local 8080" >nul 2>&1
netsh advfirewall firewall add rule name="Rota Proxima - Rede Local 8080" dir=in action=allow protocol=TCP localport=8080 remoteip=LocalSubnet profile=any
if errorlevel 1 (
  echo.
  echo ERRO: o Windows nao conseguiu criar a regra do Firewall.
) else (
  echo.
  echo OK: porta 8080 liberada para aparelhos da rede local.
)
echo.
pause
