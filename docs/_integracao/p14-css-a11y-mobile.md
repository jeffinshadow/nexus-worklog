# p14-css-a11y-mobile — CSS: foco visível, zoom, contraste, transbordo no celular e acabamento do desktop

Branch `lab/p14-css-a11y-mobile`. Arquivos: `web/static/css/app.css`, `web/static/css/tokens.css`,
`web/static/js/renewals.js` (só a marcação da linha). Sem backend, sem rota nova, sem dependência; `?v=166` intacto.
Nada foi acrescentado no fim do `app.css` (a última regra nova está perto da linha 1520 de 1845).

## Linhas para o CHANGELOG

- Acessibilidade: com zoom de 200% o foco do teclado não fica mais escondido atrás da barra de baixo e do botão
  flutuante (WCAG 2.4.11).
- Acessibilidade: o cartão "Rotina na hora" nunca passa da altura da tela (rola por dentro) e, com pouca altura,
  desce para a borda.
- Configurações no celular (até 480 px): os botões das chaves e dos webhooks descem para a linha de baixo; some a
  rolagem lateral a 320 px e o endereço do webhook não sai mais com uma letra por linha.
- Contorno dos campos (input, select, textarea) com contraste de 3:1 ou mais nos dois temas (token novo
  `--field-line`; `--line-2` não mudou).
- Links no meio de um texto agora são sublinhados (não dependem só da cor).
- Horário da rotina concluída sem a transparência que derrubava o contraste.
- Link do chamado no cartão com 24 px de altura no computador.
- Alto contraste do sistema (forced-colors): o item atual do menu, o chip ligado e a aba aberta ganham contorno.
- O seletor em pílula (`.seg`) também pinta o botão marcado com `aria-pressed`.
- Endereço ou caminho colado no título não alarga mais a tela (Tarefas, Histórico, Busca e a lista do Projeto).
- Celular: campos com 16 px no toque (o Safari do iPhone não dá mais zoom ao focar) e "Lembrete com hora" na linha
  inteira até 480 px.
- Celular deitado com recorte: barra do topo, conteúdo e diálogos de tela cheia respeitam a área segura lateral.
- "Desde o último dia útil" no celular: o título ocupa a linha e projeto e tempo descem.
- Tarefas no computador: uma rolagem só; a coluna vai até o fim da janela pela posição real.
- Configurações no computador: o índice das seções acompanha a rolagem.
- Gráficos de Meu mês e Equipe: o gráfico não passa de 286 px, então o rótulo não cresce em quadro largo.
- Vencimentos: "Virar tarefa" e "Renovei" na mesma coluna em todas as linhas; rótulo de projeto do "Tempo por
  projeto" mais largo no computador.
- Menu compacto (1024 px): o cronômetro fica encaixado no trilho (ponto, tempo e parar) em vez de flutuar sobre os
  cartões.

## Decisões e desvios da proposta

- **Rótulo de projeto (ux-desktop #12)**: a proposta pedia largura pelo conteúdo (`max-content`, teto de 40%). Cada
  linha de `.sum-bar` é uma grade separada; com largura pelo conteúdo as barras deixariam de começar na mesma
  coluna. Ficou `max(140px, min(40%, 240px))`: igual em todas as linhas, nunca menor que hoje. É CSS, não
  `renewals.js`. No celular (390 px) a coluna continua com 140 px e "Datacenter e Servidores" segue com reticências.
- **Gráficos (ux-desktop #6)**: o teto é `286px / --ui-zoom` (286 px reais), para o Meu mês em 1440 não encolher.
  O caso de 12 px (Equipe em 1440) continua, como o revisor já avisava.
- **Campos a 16 px**: `16px / --ui-zoom` com `:root:root` no seletor, só em `pointer: coarse`.
- **Índice de Configurações**: fixo só no computador (min-width 861 px). No celular os quatro atalhos quebram em
  duas linhas e, somados à barra do topo, cobririam demais. Junto vai `scroll-padding-top` enquanto a tela está
  aberta, para os saltos e o foco pararem abaixo do índice.
- **Tarefas, uma rolagem**: `.main` vira coluna flex com a altura da janela só quando o quadro é o único filho da
  tela visível (`:has`). Em Equipe › pessoa (quadro com outras coisas em volta) vale a regra antiga dos 150 px.
  Janela baixa demais (coluna com menos de 320 px): a página volta a rolar.
- **Cronômetro no menu compacto**: no trilho ficam o ponto, o tempo e o botão de parar; o nome da tarefa (que abre
  a tarefa) volta ao passar o mouse, quando o menu abre. `#timer-mobile` deixou de aparecer no computador. Só CSS;
  `timer.js` não foi tocado.
- **Horário da rotina concluída**: a regra de opacidade foi retirada (o nome riscado já mostra).

## Pendências e o que não foi verificado

- **Foco com o cartão "Rotina na hora" na tela**: sem o cartão, `v01_foco.py lucas '#/hoje' 640 450 70` deu 0
  paradas 100% cobertas. Com o cartão aberto (apareceu durante o trabalho, pela hora), deu 8, todas cobertas pelo
  `.idle-card`; em `#/tarefas` a 390×844, 17. É o que o revisor já tinha medido: a regra não resolve o cartão, e o
  cartão em faixa está fora deste pacote.
- **Área segura lateral**: o Chromium do laboratório não simula recorte (`env()` vale 0). Conferi só que nada mudou
  com 0; falta olhar num iPhone deitado.
- **Zoom do Safari ao focar**: medi o tamanho da fonte (nenhum campo abaixo de 16 px com toque em 11 telas, no
  detalhe em edição e em Nova tarefa); o comportamento no iPhone não foi testado.
- **forced-colors**: não rodei com o modo ligado; a regra é a do relatório.
- **Cronômetro no trilho, estado "Voltar para «X»"**: há CSS para ele (ícone de play e dispensar), mas não o vi na
  tela; só o estado rodando, em 1024×768.
- **Detalhe em edição no celular**: com o Lembrete na linha inteira, "Prioridade" fica sozinha na linha seguinte,
  com meia linha vazia ao lado.
- **Testes automáticos**: nenhum. A suíte (pytest) roda só o `backend/` e não enxerga `web/`; a lista de arquivos
  do pacote não inclui teste. Tudo foi conferido por Playwright, à mão.
- **Resoluções**: medi 1440×900, 1024×768, 390×844, 360×640, 320×568 e 640×450, mas não todas as telas em todas as
  combinações de tema: o axe rodou nas 19 telas, nos dois temas, em 1440 e 390; o tema claro, fora isso, só nas
  capturas dos campos. Não rodei `08_medidas.py` nem `12_graficos.py` (não estão em `relatorios/ux-desktop/`);
  usei medidas próprias.
- **axe**: sem regressão contra `p01_axe_dark.json` e `p01_axe_light.json`. Saíram `link-in-text-block` (Configurações),
  `color-contrast` (Hoje) e os `target-size` do chamado. Continuam os que são de outros pacotes: `aria-allowed-attr`
  (p15), `heading-order`, e um `target-size` do título "Chamado 48402…" em Tarefas. O trio
  `landmark-one-main`/`page-has-heading-one`/`region` aparece e some entre rodadas: é a tela de abertura ainda no
  ar quando o axe mede.
- **Um commit só para o código**: as correções se misturam nas mesmas regiões do `app.css`; não separei por item.

## Capturas

Em `/srv/docker/nexus-lab/a14/.capturas-p14/` (fora do git):

- Borda dos campos, antes e depois, nos dois temas (para o dono olhar): `campos-{antes,depois}-{dark,light}-config.png`,
  `campos-{antes,depois}-{dark,light}-nova-tarefa-{1440,390}.png`.
- Celular: `depois-{390,360,320}-{tarefas,historico,busca,config}.png` (título com endereço colado, chaves e
  webhooks), `depois-{390,360}-lembrete.png`, `depois-390-vencimentos.png`.
- Computador: `depois-1440x900-*-tarefas.png`, `depois-1024x768-*-tarefas.png` (uma rolagem; cronômetro no trilho),
  `depois-1440x500-*-tarefas.png` (janela baixa), `depois-1440-config-{topo,rolado,salto}.png` (índice fixo),
  `antes-1440-vencimentos.png` e `depois-1440-vencimentos.png`, `depois-{1440,1024}-{mes,equipe}.png` (gráficos).
- Cartão de lembrete: `lembrete-{pc,zoom200,zoom400}.png`.
