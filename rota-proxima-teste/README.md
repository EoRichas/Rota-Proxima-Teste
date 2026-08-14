# Rota Próxima — Supabase

Sistema para planejamento e execução de rotas de coleta. Nesta versão, o **Supabase é o banco de dados compartilhado e também gerencia autenticação/senhas**. O servidor Python local mantém a interface web e o cálculo/otimização das rotas.

## Perfis
- **Administrador:** controle total. Dashboard, solicitações, planejamento/liberação de rotas, PEVs, recorrentes, usuários, atividades e configurações.
- **Comercial:** cadastra/edita PEVs/locais e cria/edita/cancela as próprias solicitações pendentes.
- **Gerente Comercial:** somente consulta Dashboard, Rotas, Solicitações e PEVs/Locais.
- **Motorista:** vê e executa apenas as rotas atribuídas a ele.

## Primeiro acesso
1. Execute `INICIAR_ROTA_PROXIMA.bat` no Windows.
2. Abra `http://localhost:8080`.
3. Como o banco Supabase ainda não possui usuário, o sistema pedirá para criar o primeiro Administrador.
4. Depois, cadastre Comercial, Gerente Comercial e Motoristas em **Usuários**.

A senha inicial deve ter pelo menos 8 caracteres. Usuários criados pelo Administrador precisam trocar a senha no primeiro acesso.

## Supabase
Não existe mais `routes.db` como banco principal. Os dados ficam no Supabase, portanto computador e celulares veem a mesma base quando acessam o mesmo sistema.

As senhas ficam no **Supabase Auth** e não são armazenadas em texto puro pelo aplicativo. O Administrador pode redefinir senhas de outros usuários; os demais usuários podem alterar apenas a própria senha. Após redefinição administrativa, a troca é exigida no próximo login.

Após 5 tentativas incorretas em 15 minutos, o login é bloqueado temporariamente.

## Celular
Com computador e celular na mesma Wi-Fi, o arquivo `.bat` tenta mostrar automaticamente o endereço da rede, por exemplo:

`http://192.168.0.105:8080`

Abra esse endereço no celular.

**Importante:** o Supabase deixa o banco compartilhado, mas o frontend/servidor Python ainda está rodando no computador. Para o motorista acessar pelo 4G/5G fora da empresa, a próxima etapa é publicar este servidor em um endereço HTTPS. GPS no navegador móvel também funciona de forma confiável quando o sistema estiver em HTTPS.

## PEVs iniciais
O Supabase já contém os seis PEVs iniciais informados:
- Vila Barão — Rua das Laranjeiras, 87 — 18060-590
- Jardim Portugal — Rua João Ribeiro de Barros, 1850 — 18090-602
- Lar Roma — Rua Carolina Assiari Capitani, 20 — 18051-812
- Res. Solar das Estrelas — Rua Sargento Benedito Narciso de Pinho, 80 — 18017-302
- Res. Victoria Garbim — Rua Seraphim Banietti, 470 — 18072-856
- Res. Plazza Mazzon — Rua Pedro José Senger, 600 — 18015-000

Contato padrão dessas PEVs: Osmir Torres / Síndico / (15) 97401-0846 / WhatsApp.

## Endereço e navegação
- CEP com preenchimento automático ou endereço manual.
- Coordenadas automáticas são usadas para otimização, mas não são marcadas como confirmadas.
- Google Maps/Waze recebem o endereço postal completo com número e CEP para evitar o erro de numeração observado anteriormente.
- Coordenadas manuais podem ser cadastradas para locais rurais ou endereços imprecisos.

## Solicitações e horários
O Comercial pode informar:
- data da coleta;
- janela de horário;
- **horário específico pontual** para aquela solicitação;
- prioridade;
- observações para o motorista;
- observações internas.

O horário específico não altera o cadastro permanente do PEV. Ao iniciar ou recalcular a rota, o sistema considera a hora real e tenta encaixar a parada no compromisso; se houver incompatibilidade, exibe alerta.

## Segurança e controle
- RLS no Supabase por perfil.
- Histórico geral de atividades.
- PEV excluído vai para lixeira e pode ser restaurado pelo Administrador.
- Solicitações e exclusões críticas exigem motivo.
- Usuário com histórico deve ser desativado em vez de excluído definitivamente.
- O último Administrador não pode ser desativado.
- Motorista com rota em andamento não pode ser desativado.
- Dashboard possui Central de Pendências.
- Administrador pode exportar um backup lógico em JSON.

## Serviços externos
- ViaCEP: consulta de CEP.
- Nominatim/OpenStreetMap: geocodificação.
- OSRM: matriz de distância/tempo por vias.
- Supabase: PostgreSQL + Auth + RLS.

É necessário acesso à internet para consultar o Supabase e os serviços de rota/geocodificação.


## Correção de desempenho / PEV — 12/08/2026
- Campos de horário vazios em PEV agora são enviados como NULL, evitando erro 400 do PostgreSQL.
- Cadastro/edição de PEV usa uma única RPC no Supabase para validar duplicidade, salvar e registrar auditoria.
- Requisições GET idênticas em andamento são deduplicadas no navegador.
- Validação de perfil autenticado evita chamadas concorrentes duplicadas e usa cache curto de 120 s.
- Cache do PWA atualizado para carregar a versão corrigida.


## FASTFIX3
- Consulta de CEP não depende da sessão Supabase.
- Validação estrita de 8 dígitos e cache local de CEP por 24h.
- Demais APIs permanecem autenticadas.


## Revisão para operação - 12/08/2026
- Supabase principal em São Paulo (sa-east-1).
- Sessão renova automaticamente usando refresh token.
- PEV é salvo pela RPC `save_pev`, tratando horários vazios como NULL.
- Criação de rota e vínculo das solicitações são transacionais (`create_route_atomic`).
- Chegada/conclusão/falha de parada e respectiva solicitação são transacionais.
- Reordenação das paradas é aplicada em uma única chamada ao banco.
- Consulta de CEP não exige login, mas valida exatamente 8 dígitos e usa cache local.
- Conexões HTTP externas são reutilizadas.
- Geocodificação tem cache e fallback por CEP; coordenadas automáticas não são consideradas confirmação manual.
- Ao alterar endereço de uma PEV, coordenadas antigas são limpas para evitar rota para o ponto anterior.

### Limitação de uso no celular
Em rede local HTTP (`http://IP-DO-PC:8080`), alguns navegadores bloqueiam GPS por não ser HTTPS. A execução básica da rota continua possível, mas funções que exigem localização atual (como recalcular a partir da posição do motorista) podem depender de HTTPS.
