# p07-testes — notas para o integrador

Branch `lab/p07-testes`. Só testes, `docker-compose.test.yml`, `tools/e2e` e este arquivo: nada em `backend/app` nem em `web/`.

## O que entrou

| Item | Onde | Estado |
|---|---|---|
| Matriz de permissões por rota (alta) | `backend/tests/test_matriz_permissoes.py` (8 testes) | feito, provado por mutação |
| Lacunas de segurança (média) | `backend/tests/test_lacunas_seguranca.py` (10 testes) + guarda do convite em `test_gauntlet_loop_r3.py` | feito, provado por mutação |
| Fim de semana e virada do dia (média) | `test_gauntlet_loop_r2.py`, `test_rotina_pausa.py` | feito; NÃO rodei com relógio falso (ver "Não verificado") |
| Webhook preso ao IP, laço do agendador, SMTP (média) | `backend/tests/test_aud_p07.py` (14 testes) | feito |
| Roteiros e2e com código de saída e seletores (média) | `tools/e2e/*.py`, `tools/e2e/README.md` | feito, rodados contra o a07 |
| Argon2 barato + parâmetros de produção (baixa) | `conftest.py`, `test_aud_p07.py` | feito |
| Teste do nginx deixa de ser pulado (baixa) | `docker-compose.test.yml`, `test_gauntlet_r6_c1.py` | feito (a suíte passou de "1 skipped" para 0) |
| Migrations reaplicadas em banco cheio (baixa) | `backend/tests/test_migrations.py` | feito |
| `caixa`, `papeis`, `Agora` no conftest (baixa) | `conftest.py` + 9 arquivos | parcial (ver abaixo) |

## Como a matriz funciona (e o que fazer quando ela falhar depois do merge)

A lista de rotas sai de `app.routes`. Rota nova de qualquer pacote entra sozinha; se não se encaixar, o teste falha
com a rota na mensagem. Classifique em vez de afrouxar:

- **rota sem login** (`test_toda_rota_tem_dono_ou_esta_na_lista_de_publicas`): ponha a dependência de `app/deps.py` ou,
  se é aberta de propósito, acrescente em `PUBLICAS`;
- **escrita sem `*_csrf`**: use a variante `_csrf` ou acrescente em `ESCRITA_SEM_CSRF` (hoje só `POST /api/client-errors`);
- **rota que a senha temporária alcança** (`current_user` / `web_user_csrf`): lista fechada `COM_SENHA_TEMPORARIA`
  (me, change-password, logout, logout-others);
- **prefixo**: `/api/admin/` pede `require_admin*`, `/api/viewer/` pede `require_viewer`, `/api/assign` pede
  `require_assigner*` (única exceção escrita no teste: `GET /api/assign/people` com `require_people_list`).

Diferença para a prova original: os testes de comportamento escolhem as rotas por **método e prefixo**, não pela
dependência declarada (a rota enfraquecida continua na lista e falha), e há regra para `/api/assign`.

Limite conhecido da matriz: a dependência é lida da assinatura da rota (`_dep`). Uma rota que checasse a permissão
dentro do handler, ou uma dependência nova em `deps.py` fora da tupla `DEPS` do teste, aparece como "rota sem login"
(falha barulhenta, não silenciosa): acrescente o nome em `DEPS` e, se for só do app, em `SO_APP`.

## Prova por mutação

Cópias mutantes de `backend/app` em `/srv/docker/nexus-lab/relatorios/testes-qualidade/mut/` (geradas do commit
`06470cf`, o mesmo do `main` deste branch), montadas por cima de `/app/app` num projeto compose à parte; o repositório
de trabalho não foi alterado. Rodei `test_matriz_permissoes.py`, `test_lacunas_seguranca.py` e
`test_gauntlet_loop_r3.py`: código de hoje `36 passed`; **os 16 mutantes morrem**:

- rota: `rota_papeis_sem_admin`, `rota_redefinir_senha_sem_admin`, `rota_bloquear_sem_admin`,
  `rota_viewer_mes_sem_papel` (3 testes cada: regra de prefixo, usuário comum, chave de API),
  `rota_excluir_conta_sem_csrf` (2), `rota_enviadas_sem_papel` (2; era o que a prova original deixava vivo);
- lacunas: `logout_nao_apaga_sessao`, `sessao_vencida_vale`, `troca_senha_sem_conferir_atual`, `cookie_sem_httponly`,
  `limite_troca_senha_desligado`, `limite_link_desligado`, `remover_aparelho_de_outro`, `remover_passkey_de_outro`,
  `login_conta_bloqueada` (1 teste cada);
- `convite_antigo_apos_reset_do_admin` (a guarda `invite_pending` do aceite do convite): morre em
  `test_convite_antigo_nao_vale_depois_de_redefinir_a_senha`, que agora emite um link de convite válido direto por
  `links.issue` (o "Redefinir senha" também invalida os links, e essa defesa repetida escondia a falta da guarda).

`test_aud_p07.py` e `test_migrations.py` não tinham mutante pronto; fiz quatro, em cópias fora do repositório, e os
quatro morrem: conexão do webhook pelo nome em vez do IP validado (3 testes falham), `try/except` do push tirado de
`_passes` (falha `...os_outros_rodam[push]`), `starttls` tirado do `mailer` (falha o teste da porta 587) e uma
migration `999` com `UPDATE worklog_tasks SET title = title || '!'` (falha `test_migrations.py`, com a tabela na
mensagem). Não fiz mutante para: os `try/except` do e-mail, da agenda e da faxina (cobertos pelo mesmo teste
parametrizado, não provados um a um), a recusa de IP interno no envio, o login do SMTP e os parâmetros do Argon2.

## Tempo da suíte

A máquina estava com 24 agentes rodando suítes ao mesmo tempo (carga média entre 40 e 70), então os números
abaixo são ruidosos; a comparação que vale é a feita uma atrás da outra.

| Medida | Resultado |
|---|---|
| `main`, suíte inteira, no começo do trabalho | 592 passed, 1 skipped em **57,0 s** |
| este branch, suíte inteira (33 testes a mais, 0 pulados) | 626 passed em **54,4 s** (com roteiros e2e rodando ao mesmo tempo); a execução final, com carga acima de 60: 626 passed em 108,6 s |
| mesmos 593 testes do `main`, conftest original, uma atrás da outra sob carga | 199,5 s |
| mesmos 593 testes do `main`, só com as 3 linhas do Argon2 barato, sob carga | 103,0 s e 79,5 s |

Leitura honesta: o ganho do Argon2 barato aparece (cerca de metade do tempo na comparação lado a lado, como no
relatório: 60 s para 30 s), mas eu não consegui uma medida limpa de "antes e depois" com a máquina parada. A 1ª das
quatro execuções lado a lado (conftest original) eu perdi por erro meu na captura da saída. A suíte final não ficou
mais rápida que a do `main` em tempo de relógio porque ganhou 33 testes (a matriz chama cada rota 6 vezes, ~10 s).

## O que rever depois do merge dos outros pacotes

- **(a) p01, limitador de login / logout-others**: `test_trocar_senha_exige_a_senha_atual_e_tem_limite` conta 10
  tentativas de troca de senha no `login_limiter` (chave `pw:<id>`), e `test_links_tem_limite_de_tentativas_por_ip`
  conta 30 no `link_limiter`. Se o p01 mudar esses números ou a chave, ajuste os laços. Os testes da matriz fazem
  poucos logins CERTOS por teste (não dependem de o IP contar só falhas). Rota nova de `/login/options` precisa
  entrar em `PUBLICAS`. O `conftest` agora zera **todo** `RateLimiter` de qualquer módulo `app.*` entre os testes
  (antes era uma lista à mão): limitador novo do p01/p08 não precisa ser acrescentado.
  `test_aparelho_de_outra_pessoa_nao_e_removido` insere em `push_subscriptions` direto e não usa logout-others.
- **(b) p10, no-store e handlers de erro em `main.py`**: a matriz confere o **status** e um trecho do `detail`
  ("CSRF", "restrito", "só pelo app", "só de leitura", "troca de senha", "expirada", "bloqueado"). Se o handler novo
  mudar o corpo dos erros 401/403 (não só acrescentar cabeçalho), esses trechos precisam ser revistos.
  `test_cookie_de_sessao_e_httponly_e_samesite_strict` lê `set-cookie` do login.
- **(c) p12, `notify._passes`**: `test_agendador_um_servico_falha_e_os_outros_rodam` confere só "um falha, os outros
  rodam na mesma passada", sem ordem. Depende de: assinatura `_passes(tz, agenda, push)`; o e-mail ser chamado por
  `notify.run_once` (trocado por nome no módulo); a faxina ser `routers.photos.cleanup` na hora cheia; o laço dormir
  com `asyncio.sleep`. Se o p12 acrescentar um serviço à passada, acrescente-o em `SERVICOS` e em `_uma_passada`.
  A "reserva do e-mail em falha de conexão" não é exercitada aqui (os testes do SMTP param no `mailer.send`).
- **(d) p08, limite em `/api/assign`**: a matriz chama `POST /api/assign` umas 5 vezes por teste, sempre recusada
  antes do handler (401/403). Se o limite do p08 ficar numa dependência que roda ANTES da autenticação, pode virar
  429 na matriz. `test_chave_de_leitura_nao_escreve_em_rota_nenhuma` faz ~120 chamadas com a mesma chave (o
  `token_limiter` é 240/min): se o número de rotas de escrita dobrar, reveja.
- **(e) p02, `ANY_SQL` das equipes**: nenhum teste deste pacote depende do escopo de equipe. `test_migrations.py` cria
  uma equipe com dois membros só para ter linha em `teams`.
- **`test_migrations.py`**: exige linha em 15 tabelas depois de popular pela API. Se um pacote mudar o corpo de alguma
  rota usada em `_popular` (projects, worklog, notes, checklist, recurring, pause, renewals, calendar, tokens, teams),
  o teste falha no `_ok` com o 422 na mensagem. Migration nova que semeie dado de forma não idempotente falha aqui:
  é o defeito que o teste procura.
- **`docker-compose.test.yml`**: uma linha nova em `volumes` do serviço `tests` (`./web/nginx.conf:/web/nginx.conf:ro`).
  Quem roda a suíte por outro caminho (sem esse compose) vê `test_nginx_nao_grava_a_rota_do_link` FALHAR (antes pulava).
- **Ajudantes no conftest**: `caixa` (fixture), `papeis` e `Agora` agora existem em `conftest.py`. Arquivo novo
  (`test_aud_<id>.py`) que defina a sua própria `caixa` continua valendo (a do arquivo ganha da do conftest).
  `PH_PRODUCAO` é o `PasswordHasher` original; `security._ph` na suíte é o barato (`t=1, m=8`). Teste de outro
  pacote que confira custo/parâmetro do hash pela suíte vai ver o barato.

## Roteiros e2e (rodados contra o a07, semente restaurada, backend reiniciado entre eles)

| Roteiro | Antes (relatório) | Agora |
|---|---|---|
| `e2e_edicao` | 15 OK, 1 FALHA, rc=0 | 16 OK, rc=0 |
| `e2e_tema_convite` | 8 OK, 9 FALHAS, rc=0 | 17 OK, rc=0 |
| `e2e_instalar` | 27 OK, 1 FALHA, rc=0 | 29 OK, rc=0 |
| `e2e_convite desktop` / `mobile` | exceção | 25 OK / 25 OK, rc=0 |
| `e2e_objetivos desktop` / `mobile`, `e2e_tour desktop`, `e2e_passkey`, `tour_paradas desktop` | limpos | 22 / 20 / 56 / 10 OK / sem erro de JS, rc=0 |

- Todo `e2e_*.py` termina com `sys.exit(1)` se houver FALHAS ou erro de JS (`tour_paradas.py`: erro de JS). Visto
  funcionando: a 1ª execução do `e2e_tema_convite` saiu com rc=1 por uma FALHA real (abaixo).
- `e2e_edicao`: o interruptor virou "Receber avisos por e-mail" e o campo da API é `email_on` (era `morning`).
- `e2e_tema_convite`: espera 4 s antes de enviar o pedido (`FILL_MIN` de 3 s). A conferência do avatar supunha conta
  sem foto; a conta de demonstração tem foto: agora aceita foto OU ícone padrão, nunca letra.
- `e2e_convite`: o cartão "Esta semana" (`.sum-week`) saiu do Hoje (hoje é o resumo do último dia útil,
  `summary.js`). O trecho passou a conferir o resumo atual (`.sum-card` com 3 totais, sem setas de semana).
  **Rever**: troquei o que o trecho confere, porque o que ele conferia não existe mais; se a intenção era cobrir a
  revisão da semana, falta um roteiro para ela.
- `e2e_instalar`: cria a própria tarefa atrasada para o número no ícone e apaga depois.
- Não rodados: `e2e_sem_sinal` e `e2e_notificacoes` (precisam de SSH na homologação), `e2e_fotos` (precisa de
  imagens na pasta de saída), `e2e_tour mobile`, `tour_paradas mobile`, `auditoria_toque`, `pdfs_exemplo`. Neles só
  entrou a linha do código de saída (conferida com `py_compile`).

## Defeitos e observações achados (não corrigidos: fora do escopo deste pacote)

- `backend/tests/conftest.py` é importado duas vezes (como `conftest`, pelo pytest, e como `tests.conftest`, por
  quem faz `from tests.conftest import ...`): são dois módulos. Por isso `PH_PRODUCAO` fica guardado em
  `app.security` (`_ph_producao`), e não só no conftest (a 2ª importação guardaria o hasher barato; foi exatamente o
  que o revisor avisou e o que aconteceu na 1ª tentativa). Metade dos arquivos usa um jeito de importar e metade o outro.
- `lab.sh test NN <args>`: os argumentos substituem o comando do container; é preciso passar `pytest` na frente
  (`lab.sh test 07 pytest tests/x.py`). O exemplo das regras do laboratório (sem `pytest`) falha com
  `exec: "tests/x.py": executable file not found`.
- Na última execução da suíte inteira (máquina com carga média acima de 60) saiu no meio da saída, sem falhar teste
  nenhum, a linha de log `aviso por e-mail para a conta ... falhou: SMTPServerDisconnected: please run connect()
  first` (`routers/admin.py:34`). É uma thread de envio de verdade, de algum teste que liga `mailer.configured` sem
  trocar `threading.Thread`, terminando depois de o monkeypatch devolver o `mailer.send` real. Não apareceu nas
  outras duas execuções e não achei qual teste é; não investiguei mais. Candidato a falha intermitente sob carga.
- Nenhum defeito de `backend/app` ou `web/` apareceu com os testes novos.

## Não feito / não verificado

- **Relógio**: as duas correções (rotina todo dia; pausa conferida pelo período) seguem a prova do relatório, mas eu
  NÃO rodei a suíte com relógio falso em sábado/domingo nem atravessando a meia-noite. Hoje é segunda: os dois testes
  passam, o que não prova a correção.
- **Ajudantes (item 12), parcial**: `Agora` trocado por import em 4 arquivos e removido de 3; `caixa` idêntica removida
  de 3 (`test_convite_recuperacao`, `test_faltas_admin`, `test_para_empresas`); `_papeis` trocado em 3
  (`test_entrega7_papeis`, `test_equipe_atribuir`, `test_equipes`). Ficaram como estavam: as `caixa` com trocas
  próprias (`test_equipes`, `test_gauntlet_r3`, `test_gauntlet_r6_c1`, `test_gauntlet_loop_r3`, `test_admin_gauntlet`;
  a de `test_push` é outra coisa) e as variantes de `_papeis` escritas de outro jeito (`test_gauntlet_r3`,
  `test_gauntlet_r6_c1`, `test_para_empresas` e outros). Nenhum arquivo renomeado nem movido.
- Sem alvo de relógio com libfaketime, sem `todos.sh`, sem roteiro de sem sinal/duas contas, sem CI (decisões do dono).
- O teste em tabela do desfazer (achado 8 do relatório) não está neste pacote.
