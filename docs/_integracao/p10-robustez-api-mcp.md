# p10-robustez-api-mcp: nota para o integrador

Branch `lab/p10-robustez-api-mcp`. Sem migration (a 050 reservada não foi usada), sem dependência nova,
sem mudança em `web/`.

## Linhas para o CHANGELOG

- API: texto com NUL (`\u0000`), substituto solto (`\ud800`) ou número fora da faixa do banco responde
  **400** em JSON (`o texto tem um caractere inválido ou um valor fora do limite`) em vez de 500; o 422 de
  validação não estoura mais quando o valor recusado tem substituto solto (ele volta como `?`). A fila offline
  do celular deixa de repetir o item para sempre: com 4xx ele vai para "Não deu para aplicar".
- API: `POST`/`PATCH /api/recurring` com `steps` que não é lista nem texto responde 422 (era 500).
- API: toda resposta de `/api/` sem `Cache-Control` próprio sai com `Cache-Control: no-store`. Fotos, avatar,
  logo, calendário e exportação mantêm o cabeçalho que já tinham.
- MCP: erro de dado (NUL etc.) vira resultado `isError` que a IA lê; falha inesperada de uma ferramenta também
  (com o traceback no log do backend) em vez de HTTP 500; JSON com aninhamento absurdo (100 mil colchetes)
  responde 400.
- MCP: nomes de pessoas (quem atribuiu, quem recebeu, dono do vencimento da equipe), o chamado de tarefa
  atribuída e o vencimento alheio no `get_handoff` saem entre « »; as instruções dizem que nomes de pessoas
  também são dados. **Muda o texto** de saída: `(atribuída por «Ana»)`, `U5 «Lucas» <e-mail>`,
  `→ «Lucas»`, `[equipe Infra, de «Ana»; …]`. A passagem de turno do app e de `GET /api/summary/handoff`
  não muda.
- MCP: a chave "só registrar" (append) não tem mais o argumento `at` em `start_timer`/`stop_timer` (sai do
  `tools/list` e é recusado com `isError` se vier). A chave de escrita continua com `at`.
- Webhooks: endereço no prefixo NAT64 (`64:ff9b::/96`) é recusado, como os demais internos.
- Webhooks: cada webhook tem 20 s por passada; o destino lento deixa o resto para a passada seguinte (nada se
  perde, não conta como falha) e não atrasa os webhooks das outras pessoas.
- Webhooks: `data` dos eventos de tarefa ganha `project_name`, `minutes` e `url`.
- Admin › Identidade: logo PNG ou WebP com mais de 2000 px de lado é recusado (400), lido do cabeçalho do
  arquivo (um PNG de 13300 x 13300 cabia nos 256 KB e levava o backend a 512 MB ao gerar o PDF).
- API: nome de chave só de espaços responde 422 (virava chave sem nome) e sai sem os espaços das pontas;
  `description` de tarefa perde os espaços das pontas e, se sobrar vazia, vira `null`.
- `docs/openapi.json`: o `/mcp` documenta só o `POST` (o `GET` e o `DELETE` continuam respondendo 405);
  cada operação que aceita chave leva `x-scope` (`read`, `append` ou `write`), gerado de `deps.APPEND_ROUTES`.

## Texto para `docs/API.md` (seção Webhooks, junto da descrição do corpo)

> Nos eventos de tarefa (`entity: "worklog"`, exceto exclusão, que vai sem `data`), o `data` do **webhook**
> traz, além do estado da tarefa, três campos prontos para a mensagem:
> `project_name` (nome do projeto principal; `null` sem projeto), `minutes` (total apontado na tarefa) e
> `url` (endereço da tarefa no app: `APP_URL/#/tarefas?id=<id>`).
> Os três são calculados **na hora da entrega**, não no instante do evento: numa entrega atrasada ou repetida,
> `minutes` e `project_name` mostram o valor atual. O feed (`GET /api/history/feed`) não tem `data` e não
> leva esses campos.

Também para `docs/API.md` (quem cuidar da seção, p06):

- Entrega: "cada webhook tem até 20 s por passada; o que não coube sai na passada seguinte".
- Erros: 400 com `o texto tem um caractere inválido ou um valor fora do limite` para NUL, substituto solto ou
  número fora da faixa.
- Chaves: `x-scope` no `openapi.json`; a chave "só registrar" não manda `at` no cronômetro pelo MCP.
- `Cache-Control: no-store` nas respostas de `/api/`.

## O integrador precisa fazer

1. **Regerar `docs/openapi.json`** (`tools/openapi.py`): `test_openapi_em_dia` falha neste branch por causa do
   `x-scope` novo e da saída do `GET`/`DELETE /mcp`. É a única falha esperada da suíte.
2. Dois testes antigos tiveram **uma asserção atualizada** para o texto novo do MCP (nome entre « »):
   `tests/test_mcp_ia2.py::test_busca_e_passagem_marcam_texto_de_terceiro` e
   `tests/test_vencimento_equipe.py::test_idor_nao_membro_por_id_app_api_e_mcp`. Se outro pacote mexer nas
   mesmas linhas, vale o formato com « ».
3. Conflitos prováveis: `schemas.py` (tipos `Texto`/`TextoOpc` novos perto do topo; `description` de
   `WorklogIn`/`WorklogUpdate`; `TokenIn.name`), `main.py` (handlers e o middleware `NoStore` entre `_http_error`
   e `/api/health`; `seed_admin` e `run_migrations` intocados).

## Pendências e limites conhecidos

- O `at` do cronômetro para a chave append foi tirado **só no MCP**. Pela REST (`POST /api/timer/stop` com
  `at`) a regra é do p03 (`timer.py`, `deny_append`); sem ele, a REST continua aceitando.
- `get_handoff` pelo MCP: as aspas são postas por cima do texto de `summary.handoff_text` (arquivo fora deste
  pacote), casando o começo exato de cada linha. Se o p-dono de `summary.py` mudar o formato da linha
  (`- «título» (atribuída por Nome)`, `(chamado N`, `- rótulo — `), o teste
  `test_mcp_nome_e_chamado_de_quem_atribuiu_entre_aspas` / `test_mcp_vencimento_alheio_entre_aspas` acusa.
- `get_history` pelo MCP: o nome de quem atribuiu sai entre « » no sufixo `(atribuída por …)`, mas o
  resumo pronto que vem de `history.py` (ex.: "atribuiu … a Fulano") segue como o histórico escreve
  (arquivo do p09). O nome da equipe (`[equipe X]`, escrito pelo admin) também segue sem aspas.
- `no-store` vale para `/api/`; o `/mcp` (só POST com Bearer) ficou fora, como pedido.
- `Texto`/`TextoOpc` foram aplicados em `TokenIn.name` e na `description` de tarefa (`WorklogIn`,
  `WorklogUpdate`). Os demais campos de texto de tarefa já eram normalizados nas rotas ou nos modelos
  (título, motivo, solução, chamado). Não foi criada a recusa de motivo/dia sem `status blocked` no create.
- Logo: PNG sem `IHDR` no lugar esperado e WebP de formato desconhecido seguem aceitos como antes (não deu
  para ler o tamanho); SVG não tem limite de lado.
- Não feito, por instrução: comparar o Origin do `/mcp` com `APP_URL`, `external_ref` na atribuição, esconder a
  URL do webhook da chave read, restringir portas, `response_model`, contador de tentativas no `fila.js`.
