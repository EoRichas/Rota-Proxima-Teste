# Rota Próxima Teste

Ambiente isolado da produção.

## Supabase
- Projeto: Rota Próxima Teste
- Região: sa-east-1
- Não possui usuários, PEVs ou rotas copiados da produção.
- No primeiro acesso, a tela de configuração cria o primeiro Administrador.

## Local
Execute `INICIAR_ROTA_PROXIMA.bat` ou `python server.py` e abra `http://localhost:8080`.

## Render de teste
Crie um novo Web Service separado da produção usando este pacote/repositório e as variáveis do `.env.example`. Em Render, use `FORCE_SECURE_COOKIES=true`.

## Importante
Este ambiente não aponta para o Supabase de produção.
