# r2-01 — Excluir conta não apaga em cascata as horas de outra pessoa

## Linhas para o CHANGELOG

- **Excluir conta não apaga mais as horas de outra pessoa.** Quando uma tarefa passa de uma pessoa para outra (Admin › Contas › Bloquear ou Excluir, "Passar para outra pessoa"), o tempo já apontado continua no registro de quem saiu. Excluir depois a conta de quem recebeu apagava a tarefa e, junto, essas horas. Agora a exclusão é recusada com a frase "essa conta guarda N tarefas com horas de outra pessoa (...): transfira as tarefas para outra pessoa", e nada é apagado.
- **Excluir conta passando as tarefas leva também as concluídas que guardam horas de outra pessoa.** Elas vão para quem recebe como estão (concluídas, com a data e a resolução), entram na contagem de tarefas passadas e não geram aviso (e-mail e notificação continuam só para as abertas). Bloquear acesso com transferência segue movendo só as abertas.
- **Excluir a própria conta** (Configurações › Conta) também é recusado nesse caso: "esta conta guarda tarefas com horas de outra pessoa; peça ao admin para excluir com transferência".

## Mudanças de resposta de API (docs/API.md e openapi)

- `POST /api/admin/users/{id}/delete`: novo **409** quando a conta tem tarefa com `time_entries` de outra pessoa e, depois da transferência desta chamada (se houver `transfer_to`), ainda sobra alguma. Sem `transfer_to` é o caso normal do 409. `detail`: "essa conta guarda 1 tarefa|N tarefas com horas de outra pessoa|M outras pessoas, que seriam apagadas junto: transfira as tarefas para outra pessoa (exclua a conta escolhendo quem recebe)".
- `POST /api/admin/users/{id}/delete` com `transfer_to`: além das abertas, passam as tarefas **concluídas** da conta que guardam horas de outra pessoa (status, `completed_at` e resolução mantidos; projeto padrão de quem recebe). `transferred.count` conta todas; `transferred.emailed` só é `true` se havia aberta (o aviso lista só as abertas). Nenhum campo novo. Cada uma gera `worklog.transfer` no histórico de quem recebe, e `user.transfer_tasks` conta todas.
- `POST /api/me/delete`: novo **409** com "esta conta guarda tarefas com horas de outra pessoa; peça ao admin para excluir com transferência" (depois da conferência da senha; a sessão continua).
- `POST /api/admin/users/{id}/block`: sem mudança.
- Rotas, campos e parâmetros: nenhum novo (o `docs/openapi.json` só muda se listar os status de resposta).

## Como ficou

- `roles.others_hours(user_id)` (um lugar só): conta tarefas da conta com apontamento de outro `user_id` e de quantas pessoas. Usada em `admin.delete_user` (depois da transferência, antes de apagar) e em `me.delete_me`.
- `admin.transfer_open_tasks(..., with_others_hours=False)`: `True` só na exclusão.
- `cancel_invite` (o outro caminho que chama `roles.delete_account`): já recusa com 409 qualquer conta pendente que tenha tarefa (regra mais larga, de antes); não mexi. Não há outro `DELETE FROM users` no backend.

## O que NÃO foi feito (pendente)

- **Tela sem saída quando só há concluídas com horas alheias** (`web/static/js/admin.js`, fora do pacote): o seletor "Passar para outra pessoa" do diálogo Excluir conta só aparece se a conta tem tarefa **aberta** (`u.open_tasks`). Caso comum: B recebeu a tarefa de A, concluiu, e não tem nenhuma aberta; o admin recebe o 409 e a tela não oferece a transferência (pela API, `transfer_to` funciona). Correção sugerida: mostrar o seletor também nesse caso (precisa de um número na lista de contas ou de reabrir o diálogo com o seletor ao receber o 409). Além disso, a legenda do seletor diz "N tarefas abertas" e "As tarefas abertas saem com o resto dos dados", sem citar as concluídas que vão junto.
- A conferência e a exclusão não estão na mesma transação/instrução: uma transferência para a conta entre a conferência e o DELETE (dois admins ao mesmo tempo) ainda passaria. Fechar isso sem migration pede a condição dentro do DELETE de `roles.delete_account`; não fiz para não mudar o retorno da função usado pelos três chamadores.
- Um commit por item não foi seguido à risca: os itens 1 e 2 mexem no mesmo trecho de `admin.py` e foram num commit só; o item 4 não gerou código.
- `docs/API.md`, `docs/openapi.json` e `CHANGELOG.md` não foram editados (regra do pacote).

## O que não foi verificado

- Dos testes novos, `test_conta_sem_horas_de_outra_pessoa_exclui_como_antes`, `test_excluir_quem_recebeu_com_transferencia_leva_tarefa_e_horas` e `test_bloquear_com_transferencia_continua_movendo_so_as_abertas` passam também sem a correção (são guardas do que já funcionava, pedidas nos itens b e c); os outros três falham sem ela (conferido).
- Na tela (Playwright, 1440 e 390 px) conferi só o 409 aparecendo no diálogo Excluir conta, sem estouro lateral; o console registra a linha do navegador para a resposta 409 e, em 1440, um "Failed to load resource: net::ERR_FAILED" de origem não investigada. A tela da própria conta (Configurações › Conta) com o 409 não foi aberta no navegador (só pela API, nos testes).
- Tarefa concluída transferida que tinha chamado GLPI ligado (`external_ref` é zerado, como nas abertas) e relatórios/exportação de quem recebe uma concluída antiga: não testados.
