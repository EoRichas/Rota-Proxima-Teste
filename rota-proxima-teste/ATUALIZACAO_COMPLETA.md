# Atualização completa — 12/08/2026

Inclui:
- somente Administrador exclui rotas; Admin pode excluir rota em qualquer status;
- Admin pode excluir usuários mesmo com histórico; referências históricas ficam preservadas sem vínculo ao usuário excluído;
- Admin pode excluir qualquer solicitação;
- Comercial pode excluir as próprias solicitações pendentes e ainda não vinculadas a rota;
- Gerente Comercial pode excluir solicitações pendentes e ainda não vinculadas a rota;
- tela Atividades removida do menu; auditoria continua interna no banco;
- Relatório de Coletas para Admin e Gerente Comercial, com período, status, motorista, pesquisa e CSV;
- geolocalização gratuita com Nominatim/OpenStreetMap e fallback BrasilAPI;
- PEV encontrada por endereço completo pode ser confirmada automaticamente;
- PEV localizada apenas por rua/CEP permanece não confirmada;
- Admin pode confirmar manualmente a localização de uma PEV;
- botão Atualizar coordenadas tenta novamente todas as PEVs ainda não confirmadas.

As migrations necessárias do Supabase já foram aplicadas no projeto Rota Próxima SP nesta atualização.
