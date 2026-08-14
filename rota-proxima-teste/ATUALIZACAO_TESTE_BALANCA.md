# Rota Próxima Teste — Balança, Evidências e GPS

Build: `TESTE-BALANCA-EVIDENCIAS-2026-08-14`

Ambiente isolado de teste. Não aponta para o Supabase de produção.

## Fluxo do motorista
- Coleta: foto do material obrigatória antes de concluir a parada.
- Entrega: foto do tambor/local obrigatória antes de concluir a parada.
- A foto pode ser tirada pela câmera ou enviada do aparelho.
- Parada não realizada exige motivo e não exige foto.
- Depois que todas as paradas estiverem resolvidas, coletas realizadas entram na etapa de pesagem.
- Cada pesagem exige peso em kg + foto da balança.
- Rota com somente entregas não possui etapa de pesagem.
- A rota finaliza automaticamente quando todas as exigências forem cumpridas.

## Administração
- Admin pode resolver parada pendente como realizada ou não realizada.
- Última localização enviada pelo motorista aparece no detalhe da rota.
- Opção "Retornar à base no final" removida do planejamento.

## Relatório
- Filtro Rota removido.
- Peso coletado incluído nos indicadores, PEV, comparativo por Comercial, tabela, CSV e PDF.

## Dados de teste
- Marcelo — Comercial — senha 12345678
- Marcel — Comercial — senha 12345678
- Mauricio — Gerente Comercial — senha 12345678
- Motorista — Motorista — senha 12345678

PEVs fictícias:
- Marcelo: TESTE - Residencial Biarritz, TESTE - Lar Roma, TESTE - Ilha Bela
- Marcel: TESTE - Jardim Portugal, TESTE - Solar das Estrelas, TESTE - Plazza Mazzon
