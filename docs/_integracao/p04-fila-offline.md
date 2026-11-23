# p04-fila-offline: fila sem sinal

Branch `lab/p04-fila-offline`. Sem rota nem parâmetro novo na API (o `docs/openapi.json` não muda).

## Linhas para o CHANGELOG

- **Apontar tempo sem sinal**: o apontamento feito no detalhe da tarefa entra na fila do aparelho (com o dia em que
  foi feito) e vai quando a conexão volta. Resposta perdida não duplica mais o tempo: o reenvio usa a mesma chave
  (`external_ref`) e o aviso diz "Guardado; vai quando a conexão voltar." em vez de "Apontado".
- **Servidor fora (502, 503, 504)** passa a valer como sem conexão: a ação entra na fila em vez de dar erro.
- **Foto pesada não segura a fila**: a foto que estoura o tempo de espera vai para o fim e o resto sai antes.
- **Ação presa por erro do servidor**: na lista "Feito sem conexão", a primeira da fila ganha "Descartar" (com
  "Copiar" o texto); ela vai para "Não deu para aplicar" e as outras seguem. Nada é descartado sozinho.
- **Foto guardada sem sinal aparece na tarefa**, com a etiqueta "esperando conexão".
- **"N tarefas guardadas às HH:MM"** não é mais recarimbado quando a leitura veio da cópia guardada.
- **Leituras guardadas com mais de 7 dias** saem do aparelho ao fim de cada preparação.
- **Hoje mais leve**: o Hoje pede 50 concluídas em vez de 200 (`/board?done_limit=50`); busca, tour e a ordem das
  rotinas pedem só as rotinas (`done_limit=1`).
- **Sem sinal, o que não entra na fila** (Aguardando, checklist, editar) diz "Sem sinal: faça quando a conexão
  voltar."; três toques em Concluir viram uma ação só na fila.
- **Sessão vencida**: o app leva ao login com `?motivo=sessao` (a frase é do p01).
- **Excluir minha conta** apaga também a fila e as leituras guardadas no aparelho.

## Para o integrador

- `fila.js` exporta `BOARD_TODAY` (`/board?done_limit=50`) e `BOARD_ROUTINES` (`/board?done_limit=1`). O que fica
  guardado para sem sinal é por endereço inteiro: `today.js` e a preparação usam a mesma constante. `search.js` e
  `tour.js` usam o texto `/board?done_limit=1` (edição pontual, sem import novo); a preparação guarda esse também.
- `board.js:718` e `primeiro.js:32` (fora dos meus arquivos) ainda pedem `/board` puro. O quadro de Tarefas usa
  `/board?done_limit=20&done_offset=0`, que continua guardado. Já `pickFirst()` chamado sem o quadro pede `/board`,
  que **deixou de ser guardado pela preparação**: sem sinal, só abre se esse endereço foi visitado antes. Trocar
  `primeiro.js:32` para `BOARD_TODAY` resolve (uma linha, arquivo de outro dono).
- `api.js`: `toLogin(motivo)`; só o 401 de sessão passa `"sessao"` (o `toLogin()` de `app.js:409` fica sem motivo).
  O login já lê `next`; `motivo` é do p01.
- `api.js`: erro de rede e 502/503/504 saem com `status: 0`; o estouro de tempo leva também `slow: true`. O envio cru
  da fila (`raw`) recusa leitura que veio do cache (`X-Nexus-Cache`) com `status: 0, cached: true`.
- A fila grava dois campos novos no item (IndexedDB, sem mudar a versão do banco): `sig` (para não repetir a ação
  igual à última) e `stuck` (presa por erro do servidor). Itens antigos sem os campos seguem valendo.
- `fila.js`: `wipe()` não foi tocada (p11). `settings.js` só importa e chama antes de ir ao login. Depois do
  `wipe()`, a tela de login guarda de novo `/api/branding` (público) em `nexus-dados`.
- `app.css`: bloco no fim, `/* auditoria p04 */` (miniatura na fila e a caixa da ação presa).
- README, seção "Sem sinal" (linha ~197): falta citar que apontar tempo no detalhe da tarefa também vale sem sinal.
- A resposta de concluir com `stopped` (p03): a fila só lê `id` da resposta; campo a mais não atrapalha (não testei
  com o p03 junto).

## Pendências e limites conhecidos

- A miniatura "esperando conexão" só aparece quando o detalhe da tarefa é lido da cópia guardada (sem sinal). Foto
  que entrou na fila por estouro de tempo com rede não mostra miniatura (a releitura vem do servidor, sem a fila por
  cima). Fotos de rotina na fila também não mostram miniatura.
- O tempo que está na fila não aparece na lista de apontamentos da tarefa até ser enviado (só o aviso e a barra).
- `mes.js:275` e `board.js:509` também apontam tempo por `api.post`: sem sinal agora entram na fila em silêncio
  (antes davam erro). `mes.js` mostra o tempo como gravado; não mexi (arquivo de outro dono).
- Foto de uma tarefa criada sem sinal (passo da criação) que estoura o tempo: fica no lugar e as outras ações
  seguem, mas na volta seguinte ela é tentada primeiro de novo (não vai para o fim, para não trocar o número que
  `api.after` usa).
- "Descartar" só aparece para erro 500 de verdade; 502 a 504 contam como sem conexão e a fila espera.
- Não feito, por instrução: checklist na fila, pré-carga de todos os projetos, foto a 1280 px, envio binário.

## Como foi conferido

Suíte do backend (`tests/test_aud_p04.py`: reenvio do tempo com a mesma chave; `/board` com `done_limit` 50 e 1).
No navegador (Playwright, Chromium, 390 px e computador, ambiente a04), com roteiros fora do repositório:
resposta perdida no Apontar + segundo toque = 1 apontamento; tempo sem sinal entra na fila e sai uma vez; 502
enfileira; três Concluir = 1 item; foto lenta + anotação, a anotação sai; item com 500 descartado e o resto sai;
Hoje abre sem sinal depois da preparação pedindo só `/board?done_limit=50`; miniatura da foto na fila; servidor
parado não recarimba o "guardadas às"; leitura de 8 dias apagada e a de 1 dia mantida; 401 leva a
`/login?motivo=sessao&next=`; excluir conta deixa fila e leituras vazias.
