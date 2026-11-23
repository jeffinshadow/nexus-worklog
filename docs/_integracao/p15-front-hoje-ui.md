# p15-front-hoje-ui: Hoje, avisos, lembretes, projeto, tour e vocabulário

Branch `lab/p15-front-hoje-ui`. Só front (e uma string em `history.py`). Sem rota, parâmetro, migração ou dependência nova.

## Linhas para o CHANGELOG

- Menu ⋮ do computador não sai mais pela borda direita (a posição usa o tamanho final do menu, não o da animação).
- Avisos: no máximo 3 na pilha; o mais antigo sai e o "Desfazer" dos que ficam continua valendo.
- Lembrete de rotina/tarefa não toca enquanto houver um diálogo aberto (o botão de silenciar ficava inalcançável); volta a tocar ao fechar.
- Hoje: marcar rotina com a releitura falhando mantém a caixa e avisa "Salvo, mas a tela não atualizou."; só a falha do envio desfaz a caixa.
- Hoje: "Revisão da semana" também no diálogo da Passagem de turno (entrada no computador).
- Hoje: registro rápido pergunta "O que fez ou vai fazer?" e a linha de ajuda diz que "— 15min" no fim já conclui.
- Filtros do Hoje e períodos dos Relatórios: só `aria-pressed` (sem `aria-selected`).
- Projeto: objetivo concluído sem tarefa aberta vira uma linha ("N concluídas") que abre ao clicar; "Próximos prazos" e os objetivos são `h2`.
- Tour: a contagem espera a lista de projetos ("cinco passos" e "1 de 5" batem), as boas-vindas e o "Tudo pronto" dizem quantas paradas o passeio tem no aparelho, e a parada de Rotinas do celular tem texto próprio para a lista vazia.
- Vocabulário: "Nº do chamado ou OS (opcional)", "Renovei: nova data", "excluiu o item" (histórico), "Exclui a sua conta…", "Evidência: o que foi conferido (obrigatória nesta rotina)"; saíram as sobras de "modelos".

## Para o integrador

- **Depende do p14**: tirei o `aria-selected` dos filtros do Hoje (`today.js`) e dos períodos dos Relatórios (`reports.js`). O realce do botão escolhido vem de `.seg button.chip-btn[aria-selected="true"]` (`app.css:341`); sem o `[aria-pressed="true"]` que o p14 acrescenta a esse seletor, o escolhido fica SEM destaque. Conferir depois de juntar os dois.
- `app.css`: um bloco no fim, `/* auditoria p15 */` (estilo dos `h2` do projeto e a linha do objetivo recolhido).
- `today.js` e `tour.js`: não mexi nas chamadas do `/board` (linhas do p04).
- `backend/tests/test_aud_p15.py` é novo. Nenhum teste existente compara "removeu o item" (conferido com grep).

## Diferenças em relação ao pedido

- **Placeholder do registro rápido**: o texto pedido, "O que fez ou vai fazer (com “— 15min” já conclui)", mede 327 px e o campo tem 289 px (1440), 233 px (1024) e 218 px (390): ficava cortado antes do "já conclui" em todas as larguras. Ficou "O que fez ou vai fazer?" no campo e "com “— 15min” no fim, já conclui" na linha de ajuda logo abaixo. Se o dono preferir o texto inteiro, é uma string em `today.js`.
- **Títulos do projeto**: além de "Próximos prazos", os títulos dos objetivos e de "Sem objetivo" também viraram `h2` (projeto sem prazos teria `h1` seguido de `h3`, o mesmo erro do axe).
- **Tour, "Projeto padrão"**: quem cria o primeiro projeto no meio do tour vê esse passo com o mesmo número do passo dos projetos ("4 de 5" duas vezes), para o total não mudar no meio.
- **Tour, número de paradas**: é contado no Hoje que está por baixo do diálogo. Aberto pela Ajuda a partir de outra tela, o texto diz "um passeio rápido" / "São poucas paradas", sem número.

## Pendências

- **persona-novato #10 (rotina criada hoje depois do próprio horário não mostra o cartão): NÃO FEITO.** `lembretes.js` não tem como saber quando a rotina foi criada: `GET /recurring/reminders` não devolve a data nem a hora de criação, e `recurring.py`/`services.py` estão fora deste pacote. Proposta: o servidor devolver em cada item algo como `created_today_after` (criada hoje, com `created_at` local depois de `remind_at`) e `reminderState` devolver `null` para o cartão nesse caso; o selo "na hora" na lista do Hoje pode ficar.
- Objetivo concluído recolhido: não dá para soltar uma tarefa arrastada dentro dele enquanto está fechado (abrir antes, ou usar "Mover para outro objetivo…" no ⋮).
