# p16-config-busca: Configurações mais curta e busca por palavras

Branch `lab/p16-config-busca`. Arquivos: `web/static/js/settings.js`, `web/static/js/search.js`,
`backend/app/routers/search.py`, `backend/tests/test_aud_p16.py`. Sem migration (a 052 não foi usada), sem
dependência, sem opção nova, sem mexer em `app.css`, `app.js`, `index.html` nem `task.js`.

## Linhas para o CHANGELOG

- Busca por palavras: "backup ERP" acha "Testar a restauração do backup do ERP". A busca exige todas as palavras, em
  qualquer ordem, cada uma em qualquer parte da tarefa (título, descrição, chamado, como resolveu, anotações,
  checklist, apontamentos); quem tem a frase exata vem primeiro. Rotinas e projetos: todas as palavras no nome. A tela
  de busca destaca cada palavra.
- Configurações mais curta (de 9.133 para 6.772 px no computador; de 14.899 para 10.644 px no celular), sem tirar
  nada: em "Use o Nexus pela sua IA" cada programa abre no seu bloco; "Comandos prontos" e o formulário de webhook
  ficam recolhidos; a lista de eventos do webhook aparece depois de preencher o endereço.
- Atalhos de teclado: a lista virou o botão "Ver os atalhos"; no celular o bloco não aparece.
- Conta › "Ver o seu registro" avisa que quem administra pode redefinir a sua senha.
- Correção: o link direto para uma seção de Configurações (`#/config?aba=ia`) não rolava até ela enquanto um lembrete
  estava tocando na tela.

## O que mudou, por item

1. **Busca (qa-funcional #7).** `search.py`: a consulta é separada em palavras (sem acento, sem repetir, até 8;
   palavra de uma letra não filtra; se só houver dessas, vale a frase inteira, como antes). Uma CTE `src` junta os
   textos da pessoa (campos da tarefa numa linha, mais uma linha por anotação, checklist e apontamento) e `hit` agrupa
   por tarefa com `HAVING bool_or(f LIKE palavra)` para cada palavra; a mesma passada diz se a frase exata aparece
   (`exact`), que entra na frente do `ORDER BY`. Uma palavra só dá o mesmo conjunto e a mesma ordem de antes. Mínimo de
   2 letras, `user_id` em todas as tabelas e formato da resposta mantidos; `/api/search/similar` não mudou. Trechos
   (`hits`): continua uma consulta por tipo para a página inteira, agora com OR das palavras; o trecho é cortado em
   volta da primeira palavra encontrada.
   `search.js`: `highlight()` marca cada palavra (a busca lateral do `app.js` usa a mesma função e ganha o destaque
   sem ter sido tocada).
2. **Configurações (ux-desktop #3b/#3c, usabilidade #5, persona-novato #11).** `<details>` nativo com a classe
   `ai-config` que já existia (a da janela "Chave criada"), por isso sem CSS novo: Claude Code, Cursor, Claude
   Desktop, Gemini CLI e "Arquivo que já tinha outras coisas" (a nota que vale para os três arquivos virou um bloco
   próprio, em vez de ficar dentro de um programa só); "Ver os comandos" em Comandos prontos; "Novo webhook" em Avisar
   outro sistema. Os títulos dos painéis continuam à vista. Quem não tem chave vê em Nova chave a linha "Como ligar
   cada IA aparece ao criar a chave; o passo a passo completo está na documentação." (texto, sem link: um link novo
   dentro de frase somaria uma ocorrência de `link-in-text-block` no axe).
3. **Atalhos.** O painel fica com o interruptor e o botão "Ver os atalhos", que abre uma janela com a mesma lista de 9
   que estava na página. Texto do interruptor: "Desligados, as letras (n, q, h, t…) não fazem nada." Em tela estreita
   (até 860 px, a regra da Ajuda) ou só de toque, o painel não é montado.
4. **Transparência.** Linha fixa no fim de "Ver o seu registro": "Quem administra o Nexus pode redefinir a sua senha.
   Quando isso acontece, fica anotado no seu Histórico."

## Medições

Playwright, semente restaurada, `#/config`, 1440x900 e 390x844 (`scrollHeight`; botões e campos visíveis com todos os
`<details>` abertos e o endereço do webhook preenchido):

| conta | tela | altura antes | altura depois | botões antes → depois | campos antes → depois |
|---|---|---|---|---|---|
| Lucas (3 chaves, webhook) | 1440 | 9.133 | 6.772 | 33 → 34 | 51 → 51 |
| Lucas | 390 | 14.899 | 10.644 | 33 → 33 | 51 → 50 |
| Juliana (sem chave) | 1440 | 8.906 | 6.576 | 24 → 25 | 51 → 51 |
| Juliana | 390 | 13.354 | 9.113 | 24 → 24 | 51 → 50 |

Diferenças explicadas: +1 botão no computador é o "Ver os atalhos"; no celular o painel de atalhos some (menos o
interruptor, 1 campo, e sem o botão novo). A meta "perto de 6.000" ficou em 6.772: o que resta é a Conta (cerca de
3.250 px), que este pacote não dobra.

Conferido no navegador (as duas larguras): `<details>` abre por teclado (Enter no `summary`); eventos do webhook
ocultos sem endereço e visíveis (20 caixas) depois de digitar; criar webhook e criar chave funcionam (janelas "Webhook
criado" e "Chave criada" com as 4 configurações); `#/config?aba=ia` leva o foco ao título da seção; sem rolagem
lateral; nenhum erro de console. axe em Configurações: sobram `color-contrast` em `.notice-sub > .dialog-note`
(Avisos) e `link-in-text-block` em 2 links, todos em trechos que este pacote não tocou; não rodei o axe no `main`
para comparar número a número. axe na busca: zero.

Busca, tempos:

- Semente (Lucas: 22 tarefas, 27 anotações, 51 itens de checklist, 49 apontamentos), resposta HTTP inteira de
  `/api/search`: 20 a 60 ms com 1, 2, 4 ou 8 palavras (a primeira chamada depois de subir, 180 ms).
- `EXPLAIN ANALYZE` na semente foi medido na primeira versão (um conjunto por palavra, com INTERSECT): 2,0 ms com 1
  palavra, 5,5 ms com 2, 8,4 ms com 4, 14,2 ms com 8. Crescia com o número de palavras, então troquei pela passada
  única; a versão final não foi medida com `EXPLAIN ANALYZE`, só pelo tempo da resposta HTTP.
- Carga artificial (20.000 tarefas a mais para o Lucas, sem anotações), resposta HTTP: antes deste pacote 1 palavra
  levava 1,6 s (medido com a versão de conjuntos, que para 1 palavra é a consulta original); a primeira versão subia
  para 4,6 s com 2 palavras e 7,8 s com 4; a versão final fica em 1,2 a 1,4 s com 1, 2, 4 ou 8 palavras. O custo é o
  `nx_fold` de cada texto da pessoa a cada busca, que já existia; resolver isso pede índice ou coluna, fora deste
  pacote.

## Para o integrador

- `search.py`: a linha `ORDER BY archived, lower(name), id` (projetos), que o p12 troca por `nx_fold`, está intacta.
  A linha do `ORDER BY` das tarefas ganhou `NOT hit.exact, ` no começo.
- `search.js`: a linha do `openTask` (`card-open`), onde o p04 põe `done_limit=1`, não foi tocada, mas desceu 13
  linhas (era 149 na conta do pacote).
- `settings.js`: as linhas do excluir conta (p04) e a string "Apaga a sua conta…" (p15) não foram tocadas; desceram
  com as inserções acima delas.
- `/api/search` não ganhou rota nem parâmetro e a docstring ficou igual de propósito, para o `openapi.json` não
  mudar. Ao regerar, vale trocar a descrição para "Tarefas, rotinas e projetos com todas as palavras da busca, em
  qualquer ordem (a frase exata vem primeiro)".

## Pendências e o que não foi verificado

- O botão "Ver os atalhos" abre uma janela própria do `settings.js` com a lista de 9 que já estava lá, e não a janela
  do "?" (`showShortcuts` em `app.js` não é exportada e o pacote não podia tocar o `app.js`). As duas listas já eram
  diferentes antes. Para ficar uma só: exportar `showShortcuts` e chamar daqui.
- A correção do link direto com lembrete tocando foi conferida depois da mudança; que o defeito existia antes é
  leitura do código (a espera por `document.getAnimations()` nunca terminava com a animação sem fim do lembrete) e do
  primeiro teste, não uma medição no `main`.
- Não testei com leitor de tela, nem em aparelho de toque de verdade (só a largura de 390 px no Chromium).
- Tema claro não conferido (as capturas foram no escuro; não há cor nova).
- Busca: palavras de uma letra são ignoradas quando há outra maior ("renovar o certificado" busca "renovar" e
  "certificado"). O destaque do `app.js` (busca lateral) não foi conferido no navegador.
