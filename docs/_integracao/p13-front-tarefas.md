# p13-front-tarefas: telas de tarefa (concluir, registro rápido, cronômetro e diálogos)

Branch `lab/p13-front-tarefas`. Arquivos: `web/static/js/board.js`, `task.js`, `timer.js`, `quick.js`
e o roteiro `tools/e2e/e2e_p13_front_tarefas.py` (arquivo novo, fora da lista do pacote: é o teste).
Nada de backend, `app.css`, `index.html`, `today.js` ou `ui.js`.

## Linhas para o CHANGELOG

- Concluir uma tarefa com o cronômetro esquecido nela (mais de 12 h) agora avisa, com a ação Apontar.
- Concluir: três toques com sinal fraco mandam uma conclusão só.
- Cartão da tarefa: o leitor de tela ouve "checklist 0 de 2", "tempo apontado 40 min", "1 anotação",
  "3 fotos"; o link do chamado diz "Chamado N (abre em nova aba)".
- Registro rápido: a tarefa sem tempo responde "Ficou em aberto: «título»."; o aviso diz o que ficou no
  título sem ser lido ("20min" sem o traço, tempo acima de 24h, zerado ou antes de um marcador, "^31/02") e avisa do "@Nome" que não é
  projeto também com um projeto escolhido ao lado; "--" vale como o travessão; `!aguarda` já nasce com o
  dia para cobrar (5 dias úteis).
- Nova tarefa: sempre avisa "Tarefa criada." com Abrir; Enter e Salvar no mesmo instante criam uma só;
  fechar por Esc ou Voltar guarda o que foi digitado (Cancelar descarta).
- Detalhe: dois cliques seguidos com rede lenta abrem um detalhe só; a anotação digitada e não salva
  volta ao reabrir; a concluída sem resolução mostra "Como resolveu? (entra na busca)" com Escrever.
- Parar o cronômetro: "Apontado 10 min em «tarefa»." com Desfazer e Corrigir.
- Duração: "Não entendi a duração. Use 45 (minutos), 1h30, 1,5h ou 2:15." e "O máximo é 24h por
  apontamento."
- Textos: "Editar item", "Editar apontamento"; exclusão de rotina explica o Hoje, os relatórios e o
  Desfazer pelo Histórico.

## Pendências para o integrador

1. **Ação "Concluir" no aviso do registro rápido (today.js, do p15).** O aviso é montado em
   `today.js` (`register`, perto da linha 211), que este pacote não pode tocar. `quick.js` já exporta
   `lastOpen` (`{ id, title }` da tarefa que ficou em aberto, ou `null`). Falta em `today.js`:
   importar `lastOpen` de `./quick.js`, ler junto de `lastDone` (`const open = lastOpen`) e pôr na lista
   de ações `open ? ["Concluir", () => finishTask(open, refresh)] : null`. Sem isso o aviso novo sai
   só com "Ver" (como hoje). Com "Criar projeto" junto seriam três ações: sugiro tirar o "Ver" nesse caso.
2. **O "Ver" de today.js decide para onde rolar com `/conclu/i.test(msg)`.** Por isso os avisos novos
   da tarefa em aberto não usam a palavra "concluir" (a frase proposta no relatório, "para concluir com
   o tempo, use…", virou "para apontar, use “— 20min”"). Quem mexer nesses textos precisa manter isso
   ou trocar o teste de today.js por `lastDone`.
3. **Contrato com o p03 (`stopped` na resposta de concluir).** `finishTask` lê `r.stopped.needs_review`
   de `POST /api/worklog/{id}/finish`; sem o campo, tudo igual. Testado só com a resposta injetada pelo
   Playwright (`page.route`); com o backend do p03 junto, vale repetir o caso de
   `relatorios/qa-funcional/ui_timer_esq.py`. O `PATCH status=done` não passa pelo front (o seletor de
   situação do detalhe chama o mesmo `finishTask`), então não há leitura de `stopped` nele.
4. **p04 e `task.js` (Apontar, `r.queued`).** Na função do formulário de tempo mudei só a linha da
   validação (a mensagem da duração), uma linha acima do `try`; a linha do `api.post` e o aviso
   "Apontado …" ficaram como estavam. Se houver conflito, é nessa vizinhança.
5. **Aviso de duas linhas.** `.toast > span` corta em duas linhas (`app.css:452`); no celular cabem umas
   90 letras. As frases novas foram encurtadas para caber (com algo a dizer do título, a frase entra no
   lugar do título). "Tarefa criada (…marcadores…)" e "Registrada e concluída com … (…)" já podiam
   passar disso antes e continuam podendo.
6. **Rascunho da Nova tarefa.** Fica só na memória da página (os campos do próprio diálogo): recarregar
   o app perde. Abrir o diálogo com conteúdo próprio (compartilhar de outro app, objetivo do projeto)
   começa do zero. Os "outros projetos" não são guardados.
7. **Roteiros antigos.** `tools/e2e/*.py` que procurem os nomes "Corrigir <item>" ou "Corrigir
   apontamento de …" (agora "Editar item <item>" e "Editar apontamento de …") precisam do nome novo;
   não rodei os outros roteiros de `tools/e2e`.

## Como testar

    lab.sh up 13
    NX_BASE=http://localhost:8113 /srv/docker/nexus-lab/venv/bin/python tools/e2e/e2e_p13_front_tarefas.py

Computador 1440x900 e celular 390x844, conta Juliana da semeadura; cria tarefas "P13 …" e apaga no fim.
Casos: as 10 combinações do registro rápido (5 textos, com e sem projeto no seletor), "--", `!aguarda`
com dia para cobrar, Esc/Cancelar na Nova tarefa, mensagens de duração, Enter + Salvar = 1 tarefa,
"Tarefa criada." com Abrir, contadores no `aria_snapshot`, dois cliques = 1 detalhe, anotação que volta,
três toques em Concluir = 1 envio, "Como resolveu?" no detalhe, concluir com `stopped` injetado,
`s` com nome da tarefa, Corrigir e Desfazer, nenhum erro de console. Rodado contra o código de `main`
(controle), os casos do registro rápido, dos contadores e dos dois cliques falham, como esperado.
