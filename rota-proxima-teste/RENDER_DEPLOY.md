# Rota Próxima — deploy no Render

Esta pasta está preparada para rodar como **Web Service Python** no Render.

## Configuração já preparada

- servidor escuta em `0.0.0.0`;
- usa automaticamente a variável `PORT` fornecida pelo Render;
- `render.yaml` incluído;
- build: `pip install -r requirements.txt`;
- start: `python server.py`;
- health check: `/api/health`;
- cookies de autenticação ficam `Secure` em HTTPS;
- banco continua sendo o Supabase de São Paulo;
- `routes.db` não é usado.

## Região

O `render.yaml` usa `virginia`, porque atualmente o Render não oferece região no Brasil/South America.
O Supabase permanece em São Paulo.

## Plano

O Blueprint está configurado inicialmente como `free` para permitir o primeiro teste sem escolher um plano pago no código.
O plano Free pode dormir após período sem tráfego e não é indicado para operação diária.
Depois do teste, altere o serviço para uma instância paga no painel do Render se quiser que fique sempre disponível.

## Teste após deploy

Abra:

`https://SEU-ENDERECO.onrender.com/api/health`

Deve retornar JSON contendo:

- `ok: true`
- `build: SP-RENDER-READY-2026-08-12`
- `render: true`

Depois abra a raiz do endereço e faça login normalmente.
