# Atualização Motorista, Produção e SharePoint

## Motorista

Cada parada exige duas evidências antes de permitir **Finalizar parada** ou **Não realizada**:

- `stop_location` — foto do local;
- `drum` — foto do tambor.

A validação ocorre no frontend, no servidor e no banco de dados do ambiente de teste.

Arquivos enviados como foto também são validados pelo conteúdo real. O backend aceita apenas JPG/JPEG, PNG e WEBP válidos; um arquivo renomeado ou um conteúdo que não corresponda ao tipo declarado é rejeitado antes de entrar na fila temporária.

## Produção

O perfil `production` recebe apenas coletas concluídas pelo motorista e ainda sem pesagem.

Para cada coleta são obrigatórios:

- peso final em kg;
- foto da balança (`weighing_scale`).

A pesagem não fica mais disponível para o motorista. A rota permanece `in_progress` enquanto existir uma coleta realizada sem pesagem e é finalizada automaticamente após a última pesagem necessária.

## PEV e solicitação

Informações temporárias de atendimento não permanecem gravadas no cadastro da PEV. Período e observações operacionais pertencem à solicitação do atendimento e são reiniciados ao abrir uma nova solicitação.

## SharePoint

O armazenamento definitivo das evidências segue a estrutura reduzida:

```text
Ano
└── Mês
    └── Rota
        └── PEV
            ├── LOCAL_<hash>.jpg
            ├── TAMBOR_<hash>.jpg
            └── PESAGEM_<hash>.jpg
```

Não são criadas subpastas adicionais para Coleta, Entrega ou Pesagem.

Fluxo de armazenamento:

1. validar a imagem;
2. gravar temporariamente no Supabase Storage;
3. enviar pela Azure Function ao SharePoint;
4. registrar ID, URL, caminho, hash e status da sincronização em `route_evidences`;
5. remover a cópia temporária do Supabase somente após confirmação do SharePoint.

A Azure Function continua usando Managed Identity e Microsoft Graph; credenciais do SharePoint não são expostas ao navegador.

## Banco de teste

O Supabase **Rota Próxima Teste** já contém as proteções complementares:

- perfil `production` permitido;
- tipos `stop_location`, `drum` e `weighing_scale` permitidos;
- trigger bloqueando `completed` e `failed` sem as duas fotos do motorista;
- RLS limitando Produção às coletas liberadas para pesagem;
- trigger que finaliza a rota após a última pesagem;
- trigger que impede período e observações temporárias de persistirem na PEV.

Esta atualização é exclusiva do ambiente `EoRichas/Rota-Proxima-Teste`. O repositório principal não faz parte deste escopo.
