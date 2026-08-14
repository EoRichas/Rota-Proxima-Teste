# Geolocalização gratuita das PEVs

Esta versão não usa Google Maps API nem exige chave paga.

Fluxo de localização:
1. endereço completo (logradouro + número + bairro + cidade + UF + CEP) no Nominatim/OpenStreetMap;
2. nova tentativa sem o número;
3. fallback pelo CEP na BrasilAPI v2.

As coordenadas são salvas em `public.pevs.lat` e `public.pevs.lng`, evitando nova consulta nas próximas rotas.

No cadastro/edição, quando latitude/longitude estão vazias, o sistema tenta localizar automaticamente.
O Administrador também possui o botão **Atualizar coordenadas** em PEVs / Locais para preencher apenas registros ainda sem coordenadas.

Nenhuma variável de ambiente nova e nenhum SQL adicional são necessários.
