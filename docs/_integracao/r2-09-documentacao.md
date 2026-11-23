# r2-09-documentacao: notas para a integração

Branch `lab/r2-09-documentacao`, a partir de `lab/integracao` (3694956, 2.2.0). Só documentação e um teste: toca em
`README.md`, `docs/ADMIN.md`, `docs/API.md` e `backend/tests/test_r2_09.py`. Nenhum código de aplicação, rota,
campo, variável, migration ou tela. Não toca em `CHANGELOG.md`, `docs/openapi.json`, `version.py`, nos `?v=` nem na
seção do GLPI do `ADMIN.md`.

## Trocas no CHANGELOG.md (2.2.0), para o integrador aplicar

**(a) Parada da primeira atualização** (`CHANGELOG.md`, linhas 24 e 25, em "Avisos para quem atualiza").

Linha atual:

```
- O primeiro deploy baixa `nginx:stable-alpine` e pode baixar um `postgres:16-alpine` mais novo; o container do banco é
  recriado (`shm_size`, `cap_drop`): alguns segundos de 503. As imagens base passam a ser baixadas a cada deploy.
```

Linha nova:

```
- O primeiro deploy baixa `nginx:stable-alpine` e pode baixar um `postgres:16-alpine` mais novo; os três containers
  são recriados (`shm_size`, `cap_drop`): cerca de 20 segundos fora do ar (22 s medidos com as imagens já baixadas;
  502 e depois conexão recusada, não 503). As imagens base passam a ser baixadas a cada deploy.
```

Os 22 s são da validação de operação (10 s de 502 e 12 s de conexão recusada); não medi de novo neste pacote.

**(b) Seção "Obsoleto"** (`CHANGELOG.md`, linhas 219 e 220, fim da entrada 2.2.0).

A revisão do diff disse que a seção "não é desta versão" porque os três campos "já estavam marcados no `main`".
Conferi e **não estavam**: `git grep task_adherence origin/main -- docs/API.md` (06470cf, 2.1.0) traz a linha sem a
palavra "obsoletos", e o `CHANGELOG` de nenhuma versão anterior os cita. A marcação entrou nesta versão (commit
dcf2fe0, pacote p06). O que é verdade na crítica: a resposta de `GET /api/dashboard` não mudou (o `dashboard.py` não
foi tocado) e o app já não lia esses campos. Por isso a recomendação é **manter a seção e trocar o texto**, e não
apagá-la (o guia, seção 11 do ADMIN.md, promete que o que fica obsoleto aparece no changelog).

Linha atual:

```
### Obsoleto
- `heatmap`, `task_adherence` e `throughput` de `GET /api/dashboard`: seguem respondendo, saem na 3.0.
```

Linha nova:

```
### Obsoleto
- `heatmap`, `task_adherence` e `throughput` de `GET /api/dashboard` passam a constar como obsoletos: a resposta não
  mudou nesta versão (o app já não usava os três); seguem respondendo e saem na 3.0.
```

Não conferi em que versão o app deixou de ler os três campos (só que hoje `web/static/js` não os cita); por isso o
texto novo não dá número de versão.

## Linhas para o CHANGELOG (deste pacote)

Documentação
- Guia de administração: depois de voltar o código à mão (`git checkout` + `docker compose up -d --build`), a Saúde
  do Nexus continua mostrando o commit do último `./deploy.sh`. O guia agora avisa disso, mostra como conferir a
  versão que está no ar e como regravar `estado/deploy.json`.
- Guia de administração: avisos que faltavam para quem opera. O dump manual de `backups/` também é apagado pela
  retenção; a atualização que recria o banco tira o app do ar por cerca de 20 segundos; a senha do Postgres já
  codificada (`%XX`) igual nas duas variáveis é recusada, e como escrever uma senha com caractere especial; o nginx e
  o Postgres podem mudar de versão a cada deploy; com todas as equipes arquivadas, quem via ou atribuía só pela
  equipe deixa de ver e de atribuir.
- README: o que fica e o que sai ao excluir uma conta (as tarefas que a pessoa atribuiu ficam com quem recebeu; os
  vencimentos dela, inclusive os compartilhados com equipe, saem), o limite de 20 tarefas atribuídas à mesma pessoa
  a cada 10 minutos e o comportamento com o servidor fora do ar (502, 503 e 504 valem como sem sinal).
- Referência da API: passam a constar os objetivos de projeto (listar, criar, editar, excluir, ordenar, ordenar as
  tarefas de um bloco), o pedido de nova senha e a criação de senha pelo link (`/api/auth/forgot`, `/reset`,
  `/invite/accept`) e `GET /api/summary/week`. Completados os erros de `POST /api/assign`, as linhas removidas de
  `GET /api/assign/sent`, os erros das rotas do GLPI e os campos novos de `GET /api/admin/health`.

Testes
- Teste novo: toda rota do `openapi` que não é só do app tem de estar citada em `docs/API.md` (rota nova sem
  documentação falha a suíte). A suíte fica com 808 testes (2 novos).

## API.md e openapi

Nenhuma resposta de API mudou: nada a regenerar no `docs/openapi.json`. O `API.md` só passou a descrever o que o
código já fazia. O que entrou, conferido no código deste clone:

- `POST /api/assign`: `Retry-After` do 429 = segundos até a mais antiga das 20 sair da janela; atribuição cancelada
  conta; fora das equipes, sem registro próprio ou bloqueado = 404; na equipe e sem o aceite = 403; a si mesmo = 400.
- `GET /api/assign/sent`: toda linha `removed` vem com `description`, `due_date`, `completed_at` e `blocked_reason`
  nulos, `priority` 2 e `editable`, `cancelable`, `late` falsos; conta excluída sem registro da saída:
  `ended = {kind: "removed", at: null}`.
- `PATCH /api/assign/{id}`: 403 também quando não compartilham mais equipe (vale no cancelar).
- `GET`/`PUT /api/notifications`: o e-mail "Sua semana" abre com a frase "Hoje (DD/MM) há N tarefas em aberto".
- GLPI: `PUT /api/me/glpi` 403 para conta sem o papel Usuário e 422 com token fora de 10 a 200 caracteres;
  `POST /api/me/glpi/sync` e `POST /api/admin/glpi/test` com 429 no mesmo limite de 5 por minuto por pessoa; o teste
  responde 400 sem endereço salvo.
- `GET /api/admin/health`: `now`, `version.number`, `scheduler_last_pass` e `email.scheduler`.
- Rotas que não estavam no `API.md`: `POST /api/auth/forgot`, `/invite/accept` e `/reset`; `GET /api/summary/week`;
  `GET`/`POST /api/projects/{id}/objectives`; `PATCH`/`DELETE /api/objectives/{id}`;
  `POST /api/projects/{id}/objectives/order` e `/tasks/order`. `GET /api/export/{kind}` e as rotas de
  `/api/templates` já estavam descritas, só não com o caminho que o teste procura.

Já estavam certos e não mudei: 429 com `Retry-After` em `POST /api/assign`; `to_name`, `to_email` e `ended.reason`
da conta excluída em `/sent`; 403 do `PATCH` com o aceite desligado; `POST /api/worklog` com `external_ref`
existente, `status: "done"` e data inválida = 400; chave "só registrar" com `at` além de 5 min = 403 em
`/timer/start` e `/timer/stop`.

## Teste de documentação (`backend/tests/test_r2_09.py`)

Não havia teste equivalente (`test_openapi_em_dia` compara o `openapi.json` com o app, não com o `API.md`). A regra:
a rota conta como citada quando o `API.md` traz, entre crases, o método e o caminho, inteiro ou sem o prefixo da
seção (`POST /{id}/finish` debaixo de "## Tarefas — `/api/worklog`"); o nome do parâmetro não importa. Sem as
linhas novas do `API.md` o teste falha e lista as 14 rotas (rodei assim). **Consequência para os outros pacotes da
rodada 2:** rota nova aberta à chave de API ou pública, sem uma linha no `API.md`, quebra este teste na integração.

As 9 rotas só do app que o `API.md` também não cita ficaram de fora do teste e da documentação, como o pacote pede:
`POST /api/admin/users/{id}/invite`, `GET /api/recurring/{id}/photos`, `PUT /api/me/default-project`,
`PUT /api/me/theme`, `GET /api/viewer/users/{id}/dashboard`, `/projects` e `/reports/export`,
`GET /api/admin/invite-requests` e `POST /api/admin/invite-requests/{id}/decline`.

## O que NÃO foi feito

- `teams_on` em `GET /api/auth/me` está descrito como "a instância tem equipes"; o código diz "há equipe cadastrada,
  mesmo arquivada" (`teams.any_active`). O pacote manda não mexer nessa linha; fica para o integrador decidir.
- Nada sobre exclusão de conta com horas alheias, troca de endereço do GLPI e espera do SMTP (são de outros pacotes).
- `MAIL_SCHEDULER=false` também para a faxina e a sincronização do GLPI? A tabela de variáveis do ADMIN.md diz só
  "agendador de avisos". Não conferi e não mexi.

## O que não foi verificado

- Chamei de verdade, no a09 reconstruído com este branch (e restaurei a semente depois): o 429 com `Retry-After`
  na 21ª atribuição à mesma pessoa (e 201 para outra); 400, 404 e 403 de `POST /api/assign`; 400 do teste do GLPI
  sem endereço, 422 do token curto e a resposta do `sync` sem conexão; `GET /api/summary/week`; criar objetivo (201,
  repetido 200 com `existing`, título igual 409), os 400 das duas ordenações; 404 de `/api/export/<outro>`; `forgot`
  sem conta (200) e os 400 de `/reset` e `/invite/accept` com link inválido; os campos novos de
  `GET /api/admin/health`; gravar `estado/deploy.json` com o comando do guia e ver o commit aparecer sem reiniciar.
  O resto saiu só da leitura do código: os 429 de `forgot`, do convite e do GLPI, o 403 do `PATCH` fora da equipe,
  as linhas `removed` de `/sent` com conta excluída, o `PATCH` e o `DELETE` de objetivo, o caminho feliz de `/reset`
  e de `/invite/accept`, e os erros de GLPI que dependem de um GLPI configurado.
- A parada de cerca de 20 s: é o número da validação de operação, não medido aqui. Com a imagem do banco igual
  (só backend e nginx recriados) a parada deve ser menor, mas não medi e o guia não dá número para esse caso.
- Senha com caractere especial crua em `POSTGRES_PASSWORD` e codificada na `DATABASE_URL`: simulei a regra do
  `deploy.sh` e conferi que o psycopg decodifica `%40` na URL; não subi um banco com uma senha assim.
- O texto do e-mail "Sua semana": lido em `notify.build_weekly` e `report_pdf._lede`, sem mandar o e-mail.
- "Sem sinal" do README: conferido em `fila.js`, `api.js` e `sw.js`, sem navegador (nenhuma tela mudou).
