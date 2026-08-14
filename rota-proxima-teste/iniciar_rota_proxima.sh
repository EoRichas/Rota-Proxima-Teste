#!/usr/bin/env sh
set -e
cd "$(dirname "$0")"
python3 -c 'import requests' >/dev/null 2>&1 || python3 -m pip install -r requirements.txt
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "Rota Próxima em http://localhost:8080"
[ -n "$IP" ] && echo "Celular na mesma rede: http://$IP:8080"
python3 server.py
