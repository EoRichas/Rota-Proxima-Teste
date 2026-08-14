# func-rota-proxima

Azure Function para gravar fotos do Rota Próxima diretamente na pasta SharePoint `Rota - PEVS`.

## App settings necessários
- `AZURE_CLIENT_ID`: client ID da managed identity `func-rota-proxima-uami`
- `SHAREPOINT_DRIVE_ID`: drive ID da biblioteca Documentos
- `SHAREPOINT_ROOT_FOLDER_ID`: item ID da pasta Rota - PEVS

## Rotas
- `GET /api/health` — exige Function Key
- `POST /api/upload-rota-pev` — exige Function Key

O upload recebe JSON com imagem em base64.
