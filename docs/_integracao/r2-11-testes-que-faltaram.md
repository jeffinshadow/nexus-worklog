# r2-11: testes que faltaram

Pacote só de testes: um arquivo novo, `backend/tests/test_r2_11.py` (22 testes: 18 passam, 4 ficam em
`xfail(strict=True)` por achado). Nada de `backend/app`, `web/`, `conftest.py` ou teste antigo mudou.
Suíte inteira em 23/11/2026: `824 passed, 4 xfailed` (eram 806).

## Linhas para o CHANGELOG

Nada muda para quem usa. Se a versão listar trabalho interno:

- Testes: cada ação que tem "Desfazer" no Histórico (36) agora é feita, desfeita e conferida contra o banco; ação nova
  sem teste faz a suíte falhar com o aviso de onde acrescentar.
- Testes: os dois testes que falhavam no fim de semana e na virada do dia agora rodam em sábado, domingo e
  atravessando a meia-noite.

## Mudanças de resposta de API (docs/API.md, openapi)

Nenhuma.

## O que foi feito, item a item

1. **Desfazer em tabela** (`DESFAZ`, `test_desfazer_devolve_o_estado_e_so_vale_uma_vez`): para cada uma das 36 ações
   de `history.UNDOABLE`, prepara, fotografa 12 tabelas, faz a ação pela API, desfaz pela API e compara a fotografia;
   o 2º desfazer dá 409 "já foi desfeita" e não mexe em nada; ação de outra conta ou inexistente dá 404.
   `test_toda_acao_desfazivel_tem_linha_na_tabela` falha dizendo a ação e onde pôr a linha.
   As 36 rodam na mesma conta, num teste só (36 contas custavam ~11 s); a falha lista cada ação quebrada.
2. **Relógio**: os DOIS testes antigos são importados e rodados de novo com a data da app trocada (sábado 28/11 e
   domingo 29/11/2026), e atravessando a meia-noite de sábado para domingo (a pausa: antes do 1º e antes do 2º
   desfazer; o ranking: entre marcar a rotina e ler os painéis). 7 testes.
3. **PDF de projeto**: 520 tarefas com tempo (SQL direto), dados pelo caminho da rota (`resolve_range` +
   `get_report_range`), e `report_pdf._time_by_task` desenhando num PDF de verdade com os textos anotados: 500 linhas,
   "+ 20 outras tarefas" com a soma do resto, "Total" igual ao `summary.minutes` da capa e à soma no banco.
4. **Mutantes**: um teste por serviço do agendador e um do envio do webhook (cadastro com IP público, o DNS muda,
   `webhooks.run_once()` de verdade não conecta e grava a falha).
5. **Devolução**: atribuir, apontar 3 tempos (dois dias) e uma anotação, devolver pela API, conferir a lápide gravada
   pela rota (`user_id` por apontamento), desfazer pela API e conferir cada apontamento (id, dono, tarefa, dia,
   minutos, criação) igual ao de antes; outra conta não desfaz (404).
6. **Webhook de admin**: ver "Achados".

## Mutantes aplicados à mão (no clone, desfeitos com `git checkout`)

| Mutante | Teste que falhou | Os outros testes do arquivo |
|---|---|---|
| (a) `notify._pass` sem o try/except do e-mail | `test_agendador_email_que_estoura_nao_derruba_a_passada` | os de agenda e faxina passaram |
| (b) sem o try/except da agenda | `test_agendador_agenda_que_estoura_nao_derruba_a_passada` | os de e-mail e faxina passaram |
| (c) sem o try/except da faxina do banco | `test_agendador_faxina_que_estoura_nao_derruba_a_passada` | os outros passaram; **`test_aud_p07.py` inteiro também passou** (o parametrizado antigo não troca `notify.faxina`: o mutante sobrevivia) |
| (d) `webhooks.post` que, recusado o endereço, conecta assim mesmo no IP resolvido | `test_webhook_cadastrado_com_ip_publico_nao_envia_...[interno]` e `[misto]` | — |
| teste antigo do ranking de volta à rotina de dias úteis | os 2 de fim de semana e o da meia-noite do ranking | — |
| teste antigo da pausa de volta a contar linhas | `..._atravessando_a_meia_noite[antes-do-1o-desfazer]` | o `[antes-do-2o-desfazer]` passou (certo: ali a contagem não muda) |
| `MAX_ROWS = 400` | o do PDF | — |
| desfazer de `note.update` que não regrava o texto | a tabela, dizendo só `note.update` | — |

## Achados (NÃO corrigidos: viram item para o dono)

1. **Webhook de conta admin entrega o log administrativo.** Evidência
   (`test_webhook_do_admin_nao_entrega_o_log_administrativo`, xfail estrito; com `--runxfail` a falha mostra):
   o admin cadastra um webhook com os eventos padrão, abre `/api/viewer/users/{id}/dashboard` de outra pessoa (rota de
   verdade, grava `master.view` com ator `admin`) e a passada seguinte entrega
   `('master.view', 'user', 2, None)`: ação, entidade e o id da pessoa vista; `data` vai `null` (o e-mail da pessoa não
   vai). `webhooks._deliver` lê o `audit_log` sem o filtro de ator que o feed por chave e o MCP ganharam no p09. A
   decidir: filtrar como na chave (mantendo `worklog.transfer`) ou assumir que o webhook, cadastrado pelo app, vê o que
   o app vê.
2. **Desfazer a exclusão não devolve a data de criação** de item de checklist, projeto e vencimento
   (`test_desfazer_exclusao_devolve_a_data_de_criacao`, 3 casos em xfail estrito): voltam com `created_at = agora`
   (anotação, apontamento e tarefa voltam com a data original). No projeto a data entra em
   `reports.project_first_day` ("projeto inteiro"), mas só pesa se não houver tarefa nem tempo mais antigo; no
   checklist e no vencimento não achei uso além da ordem. A tabela geral compara essas três tabelas sem a coluna.

## O que NÃO foi feito

- Os achados acima não foram corrigidos (regra do pacote).
- O "alvo `relogio`" proposto pela auditoria (suíte inteira com libfaketime) não foi feito: não era item.

## O que não foi verificado / limites

- **O relógio falso troca só o "hoje" da app** (`app_today` em todo módulo que o importa), não o `now()` do Postgres
  nem os poucos `datetime.now(tz)` diretos (texto "hoje 15h" de lembrete, hora de geração do PDF). Para o fim de
  semana ser reproduzido, a criação da rotina é levada por SQL para o dia falso. A suíte inteira NÃO foi rodada em
  sábado/domingo; só os dois testes. Não há fuso por pessoa no app: "o fuso da pessoa" é o `APP_TZ`.
- A virada do dia foi testada em três pontos escolhidos, não em todo ponto possível dos testes antigos.
- O PDF: confere a função que desenha a tabela e os dados; o binário final (`build_report_pdf`) não é aberto.
- No desfazer em tabela, cada ação tem UM cenário (o comum). Variações (pausa copiada para rotina nova, projeto com
  extras/promovidas, foto de rotina, vencimento de equipe renovado por colega) seguem só nos testes antigos.
  As 36 ações compartilham a conta: um caso que deixe lixo pode sujar o seguinte (cada um fotografa o seu "antes").
- Tempo: o arquivo soma ~12 s de CPU em série com a máquina carregada (a tabela do desfazer são ~5,5 s; o PDF ~1 s),
  acima dos "~10 s" pedidos se contados em série; com os 8 processos da suíte são ~2 s a mais de relógio. A suíte
  levou 78 s nesta máquina com outras suítes rodando ao mesmo tempo (não medi sozinha).
- (d) O mutante do webhook foi um só (o envio conecta mesmo recusado); outras formas de furar o envio não foram
  tentadas.
- Devolução: a rota recusa devolver tarefa com tempo de outra conta (409), então "cada apontamento ao user_id certo"
  só pode ser conferido com apontamentos de quem devolve; a lápide com dono alheio continua coberta só pelo teste
  simulado do p09.
