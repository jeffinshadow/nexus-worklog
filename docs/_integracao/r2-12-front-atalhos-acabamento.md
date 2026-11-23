# r2-12 — Front: atalhos, busca lateral e acabamentos no celular

Branch `lab/r2-12-front-atalhos-acabamento`, a partir de `lab/integracao` (3694956). Só front: nenhuma rota, campo ou migration.

## Linhas para o CHANGELOG

- **Atalhos de teclado**: "Ver os atalhos", em Configurações, abre a mesma janela da tecla `?` (antes era uma cópia com outros rótulos). Continua abrindo com os atalhos desligados.
- **Busca do menu lateral**: as setas agora marcam a sugestão sem tirar o cursor do campo, e Enter abre a marcada (sem nenhuma marcada, Enter segue abrindo a Busca completa). Leitores de tela anunciam o campo como caixa de combinação com a lista de sugestões.
- **Detalhe da tarefa no celular**: em edição, a Prioridade ocupa a linha inteira, como o Lembrete; não sobra mais meia linha vazia.
- **Hoje no celular**: em "Tempo por projeto", o nome do projeto aparece inteiro (a barra e o tempo ficam na linha de baixo); reticências só quando falta espaço de verdade.
- **Tarefas em janela baixa** (até 600 px de altura, no computador): a página rola sozinha, sem a segunda rolagem dentro das colunas.
- **Webhook**: a lista de eventos aparece também quando o endereço é preenchido pelo navegador (preenchimento automático).

## API / docs

Nenhuma mudança de resposta de API, MCP ou openapi.

## Para o integrador

- **`?v=`**: subir em `index.html` (mudaram `app.js`, `settings.js` e `app.css`). Não mexi.
- **`sw.js`**: nada a incluir. Não criei `atalhos.js`: `settings.js` pede a janela ao `app.js` pelo evento `nexus:atalhos` na `window` (o mesmo jeito do `nexus:help` que já existia), sem ciclo de importação e sem arquivo novo no casco.
- `index.html` não mudou: os atributos do combobox são postos pelo `app.js`, onde a lista é criada.
- `tools/e2e/README.md` não está na lista do pacote: falta a linha do roteiro novo na tabela (`e2e_r2_12_front.py`: atalhos, busca lateral, celular a 390/320, janela baixa; só lê, sem `SAIDA`).
- `backend/tests/test_r2_12.py` não foi criado (não há backend nem texto estático que valha um teste).

## Como ficou cada item

1. **Atalhos**: apagada a lista de `settings.js`; o botão dispara `nexus:atalhos` e o `app.js` abre `showShortcuts`. A caixa "Atalhos de uma tecla" não mudou.
2. **Busca lateral**: campo com `role=combobox`, `aria-autocomplete=list`, `aria-haspopup=listbox`, `aria-controls=side-sugg-list`, `aria-expanded` e `aria-activedescendant`; a lista é `role=listbox` com `role=option` (`aria-selected`). Mudança de comportamento: antes as setas levavam o foco para os botões das sugestões; agora o foco fica no campo e a sugestão marcada ganha contorno. "Ver todos os resultados" fica fora da lista (botão comum, alcançável por Tab e clique). Sem sugestão, não há listbox (só o aviso) e `aria-expanded` fica `false`.
3. **Prioridade (390 px)**: linha inteira quando o Lembrete existe (tarefa não concluída). Não reordenei os campos para a ordem do Tab continuar igual à da tela.
4. **Rótulo de projeto**: o corte em 140 px era a primeira coluna de `.sum-bar` (Hoje › Tempo por projeto). Até 480 px o nome vai numa linha própria.
5. **Janela baixa**: em vez de mexer no `min-height: 320px`, uma media query (`min-width: 861px` e `max-height: 600px`) solta a altura das colunas: uma rolagem só, a da página. Acima de 600 px nada muda.
6. **Webhook**: `change` além de `input`, e o valor é conferido de novo ao abrir/fechar "Novo webhook" (`toggle`).

## Verificado

- `node --check` em `app.js` e `settings.js` (node:22-alpine).
- `tools/e2e/e2e_r2_12_front.py` no a12: 33 casos ok; na base (sem as correções) 9 falham (atalhos, combobox, Prioridade, rótulo, janelas 1440x500 e 1280x360). Cobre 1440x900, 1024x768, 900x700, 1440x500, 1280x360, 390x844 e 320x640, temas escuro e claro no celular, sem erro de console.
- axe (roteiro do laboratório, wcag2a/aa/21/22 + best-practice) no Hoje com a busca aberta e uma sugestão marcada, temas escuro e claro: `aria-allowed-attr` sumiu. Sobra 1 aviso `target-size` no link "Histórico" do menu, porque a caixa de sugestões o cobre em parte enquanto está aberta (já era assim antes; não mexi).
- Webhook: com o valor posto sem `input` e só `change`, os eventos aparecem; com o valor posto sem evento nenhum, aparecem ao reabrir a seção.
- Suíte inteira (`lab.sh test 12`): 806 passed.

## Não feito / não verificado

- Não testei com leitor de tela de verdade (NVDA, VoiceOver, TalkBack): só axe e a árvore de acessibilidade do Chromium.
- Preenchimento automático real do navegador no webhook não foi reproduzido: simulei com valor posto por script e evento `change`. Se o navegador preencher sem `change` com a seção já aberta, os eventos só aparecem ao digitar ou reabrir a seção.
- O roteiro e2e oscilou: em 7 execuções, 2 falharam (uma logo depois de um `lab.sh up`, sem eu ver o caso; outra com a tela de Tarefas não desenhando os cartões em 8 s, nos casos do celular e da janela baixa). Na mesma hora o Chromium registrava `ERR_NETWORK_CHANGED` (redes do Docker de outros ambientes subindo). Pus uma segunda tentativa (recarregar) ao abrir cada tela; depois disso, 4 execuções seguidas passaram. Tratei como instabilidade do laboratório, sem prova de que não seja do app.
- Firefox e Safari não testados (só Chromium). O CSS usa `:has()`, que o `app.css` já usava.
- Janela baixa com zoom do navegador ou entre 600 e ~620 px de altura sem o aviso do assistente: não medi cada combinação; medi só os cinco tamanhos acima.
- Manual (`shadow.tec.br/nexus-manual`) e capturas de `docs/screenshots` não foram revistos para a mudança das setas na busca.
