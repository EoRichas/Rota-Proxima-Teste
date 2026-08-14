# Sincronização de fotos pelo navegador

Build: `TESTE-BROWSER-SYNC-FOTOS-2026-08-14`

- Remove a necessidade de PowerShell, tarefa agendada ou programa residente no Windows.
- Administrador recebe a tela **Fotos no computador**.
- A pasta é escolhida com a File System Access API do Chrome/Edge.
- Destino esperado: `C:\Users\balan\OneDrive - GGJ Consultoria\Área de Trabalho\Rota - PEV`.
- O navegador não expõe o caminho completo; o Administrador escolhe a pasta `Rota - PEV` manualmente.
- Fotos são copiadas do bucket privado `rota-evidencias-teste` por endpoint autenticado do Rota Próxima.
- Estrutura: Ano > Mês > Rota > PEV > Coleta/Entrega/Pesagem.
- Arquivos possuem ID da evidência no nome, evitando duplicação.
- Sincronização automática a cada 2 minutos enquanto o Rota está aberto e a permissão da pasta permanece concedida.
- Se o navegador estiver fechado, as fotos continuam no Supabase e serão copiadas em uma execução futura.
