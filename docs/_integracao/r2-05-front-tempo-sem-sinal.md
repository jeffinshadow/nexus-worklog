# r2-05-front-tempo-sem-sinal

Meu mês, quadro e registro rápido: tempo apontado sem sinal deixa de entrar na fila em silêncio.
Só front (mes.js, board.js, quick.js, api.js). Sem backend, sem migration, sem mudança de API.

## Linhas para o CHANGELOG

- Meu mês › Antes do PDF: apontar o tempo sem sinal não aparece mais como salvo. A linha mostra o valor com a marca "esperando conexão", o aviso diz "Sem sinal: o tempo sai quando a conexão voltar." e o topo deixa de dizer "Tudo completo" enquanto o tempo não entrou.
- Nova tarefa com tempo (quadro): se o sinal cai depois de a tarefa ser criada, o aviso diz que o tempo ficou guardado e sai quando a conexão voltar (antes dizia só "Tarefa criada").
- Registro rápido com "— 20min": se o sinal cai depois de a tarefa ser criada, o aviso diz que o tempo sai quando a conexão voltar, em vez de "Registrada e concluída com 20min".
- Lista colada (várias tarefas de uma vez): o aviso conta as tarefas cujo tempo ficou esperando conexão, e o Desfazer tira esse tempo da fila do aparelho em vez de tentar apagar um apontamento que ainda não existe.
- Ação que não dá para guardar (editar, checklist, Aguardando) com o servidor fora do ar (502, 503, 504) diz "O servidor está fora do ar: faça de novo em instantes."; "Sem sinal: faça quando a conexão voltar." fica só para quando não há rede.

## Mudanças de resposta de API (docs/API.md / openapi)

Nenhuma.

## O que foi feito, por item

1. mes.js: a resposta `{ queued: true }` do POST /worklog/{id}/time vira `x.waiting` (não `x.minutes`): chip `chip today` "15 min · esperando conexão" (mesma classe e texto do detalhe da tarefa), aviso, sem o chip "completa", sem pedir o tempo de novo (não duplica) e sem recarregar o mês como se tivesse mudado. Se o tempo foi para a fila e o "como resolveu" falhou (PATCH não entra na fila), a linha é redesenhada com o tempo esperando e o texto digitado mantido.
2. board.js (l.532): o retorno enfileirado do tempo acrescenta "Sem sinal: o tempo sai quando a conexão voltar." ao "Tarefa criada."; o aviso de erro "o tempo não foi salvo" não culpa mais o tempo quando ele está na fila. A l.514 (tarefa inteira criada sem sinal) já dizia "Sem conexão: tarefa guardada no aparelho" e não mudou. O quadro nunca disse "Apontado" (esse texto é do task.js).
3. quick.js: registro rápido (l.175) e lista colada (l.296) tratam a resposta enfileirada; o Desfazer do lote cancela o tempo na fila (`timeQid`) e não lê mais `.id` de resposta nula. O texto novo não casa com /conclu/i.
4. api.js: só a frase (marca `down` no erro de 502-504; a fila continua tratando como sem conexão). fila.js não precisou mudar.
5. tools/e2e/e2e_r2_05_tempo_sem_sinal.py: roteiro novo, com código de saída.
6. backend/tests/test_r2_05.py: NÃO criado. O teste pedido já existe: backend/tests/test_api_aberta.py (l.70-71, POST /worklog/{id}/time repetido com o mesmo external_ref grava uma linha só) e test_gauntlet_geral_r4.py (l.19-27).

## Prova no navegador (a05, http://localhost:8105, 23/11/2026)

`NX_BASE=http://localhost:8105 python tools/e2e/e2e_r2_05_tempo_sem_sinal.py`: 47 ok, 0 falha, em 1440x900 e 390x844, sem erro de console.

```
ok    [1440] Meu mês sem rede: aviso de fila 
ok    [1440] Meu mês sem rede: marca 'esperando conexão' com o valor 
ok    [1440] Meu mês sem rede: não diz 'completa' nem pede o tempo de novo 
ok    [1440] Meu mês sem rede: o topo não diz 'Tudo completo' 
ok    [1440] Meu mês sem rede: nada no servidor ainda 
ok    [1440] quadro sem rede: aviso de fila, sem 'Tarefa criada' nem 'Apontado' 
ok    [1440] registro rápido sem rede: aviso de fila 
ok    [1440] quadro, sinal cai no tempo: 'Tarefa criada' + aviso de fila, sem 'não foi salvo' 
ok    [1440] quadro, sinal cai no tempo: tarefa no servidor, tempo ainda não 
ok    [1440] registro rápido, sinal cai no tempo: aviso de fila 
ok    [1440] registro rápido, sinal cai no tempo: o texto não casa com /conclu/i (destino do 'Ver') 
ok    [1440] lista colada, sinal cai no tempo: aviso de fila 
ok    [1440] lista colada: 2 tarefas no servidor, tempo ainda não 
ok    [1440] lista colada: Desfazer tira as 2 tarefas (e o tempo da fila) 
ok    [1440] lista colada: depois do Desfazer nada fica no servidor 
ok    [1440] lista colada: fila vazia e sem falha de envio 
ok    [1440] servidor: Meu mês gravou 1 apontamento de 15 min 
ok    [1440] servidor: 'quadro off' = 1 tarefa com 1 apontamento de 20 min 
ok    [1440] servidor: 'rapido off' = 1 tarefa com 1 apontamento de 20 min 
ok    [1440] servidor: 'quadro meio' = 1 tarefa com 1 apontamento de 20 min 
ok    [1440] servidor: 'rapido meio' = 1 tarefa com 1 apontamento de 20 min 
ok    [1440] servidor fora (503): frase própria 
ok    [1440] sem rede: frase de sempre 
ok    [390] Meu mês sem rede: aviso de fila 
ok    [390] Meu mês sem rede: marca 'esperando conexão' com o valor 
ok    [390] Meu mês sem rede: não diz 'completa' nem pede o tempo de novo 
ok    [390] Meu mês sem rede: o topo não diz 'Tudo completo' 
ok    [390] Meu mês sem rede: nada no servidor ainda 
ok    [390] quadro sem rede: aviso de fila, sem 'Tarefa criada' nem 'Apontado' 
ok    [390] registro rápido sem rede: aviso de fila 
ok    [390] quadro, sinal cai no tempo: 'Tarefa criada' + aviso de fila, sem 'não foi salvo' 
ok    [390] quadro, sinal cai no tempo: tarefa no servidor, tempo ainda não 
ok    [390] registro rápido, sinal cai no tempo: aviso de fila 
ok    [390] registro rápido, sinal cai no tempo: o texto não casa com /conclu/i (destino do 'Ver') 
ok    [390] lista colada, sinal cai no tempo: aviso de fila 
ok    [390] lista colada: 2 tarefas no servidor, tempo ainda não 
ok    [390] lista colada: Desfazer tira as 2 tarefas (e o tempo da fila) 
ok    [390] lista colada: depois do Desfazer nada fica no servidor 
ok    [390] lista colada: fila vazia e sem falha de envio 
ok    [390] servidor: Meu mês gravou 1 apontamento de 15 min 
ok    [390] servidor: 'quadro off' = 1 tarefa com 1 apontamento de 20 min 
ok    [390] servidor: 'rapido off' = 1 tarefa com 1 apontamento de 20 min 
ok    [390] servidor: 'quadro meio' = 1 tarefa com 1 apontamento de 20 min 
ok    [390] servidor: 'rapido meio' = 1 tarefa com 1 apontamento de 20 min 
ok    [390] servidor fora (503): frase própria 
ok    [390] sem rede: frase de sempre 
ok    sem erro de console 

0 falha(s)
```

`node --check` (node:22-alpine) em mes.js, board.js, quick.js e api.js: ok. Suíte: ver o fim desta nota.

## O que NÃO foi feito

- Reabrir o "Antes do PDF" ainda sem sinal (ou recarregar a tela) mostra a tarefa de novo como "sem tempo": a marca "esperando conexão" vive só enquanto o diálogo está aberto, porque a lista do mês (/dashboard) não recebe por cima o que está na fila (fila.js `overlay` só cobre /board e o detalhe da tarefa). Quem apontar de novo ali grava dois apontamentos (cada um com o seu external_ref). Corrigir é mexer na lógica da fila, que este pacote mandou não mudar.
- Lista colada: se o tempo da fila já tiver sido enviado quando a pessoa aperta Desfazer, o desfazer da tarefa depende de o servidor aceitar (o histórico mais recente passa a ser o do tempo); nesse caso o aviso diz "já mudou (exclua pela tela)". Não reproduzi esse caso.
- today.js não foi tocado (fora do pacote): com o tempo na fila, o aviso do registro rápido ainda oferece "Como resolveu?", que sem rede responde "Sem sinal: faça quando a conexão voltar."; e o "Ver" rola para "Em aberto" (o texto novo não tem "conclu"), mesmo quando a tarefa nasceu concluída (não conferi no navegador para onde ele rola).

## O que não foi verificado

- O roteiro bloqueia o service worker (como o modelo p13): sem a cópia guardada, a releitura da tela depois de salvar sem rede rejeita com "Sem conexão com o servidor" (board.js refresh e today.js mount, comportamento anterior a este pacote); o roteiro ignora esse erro de página. Com o service worker ligado (uso real) não testei.
- "Sinal cai só na hora do tempo" foi simulado abortando o POST .../time (page.route), não com rede real instável.
- A frase do servidor fora foi provada com um 503 fabricado (page.route) num PATCH /worklog/{id}; 502 e 504 passam pela mesma linha, não foram exercitados um a um, nem com o nginx de verdade sem backend.
- O caminho de mes.js "tempo na fila + como resolveu falhou" (redesenho mantendo o texto) foi só lido, não exercitado no navegador.
- Só Chromium; nada em aparelho real.

## Suíte

`lab.sh test 05` (inteira, depois do último commit de código): 806 passed, nenhuma falha (nem test_openapi_em_dia). Semente do a05 restaurada ao fim.
