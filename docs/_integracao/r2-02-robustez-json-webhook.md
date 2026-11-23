# r2-02 — JSON muito aninhado sem 500, busca com NUL e webhook sem minutos alheios

Branch `lab/r2-02-robustez-json-webhook` (base: `lab/integracao`, 2.2.0, commit 3694956).

## Linhas para o CHANGELOG

- **Pedido com JSON aninhado demais não derruba mais a resposta.** Um corpo com mais de mil colchetes ou chaves aninhados (inclusive na tela de login, sem estar logado) respondia erro 500 e enchia o log do servidor. Agora responde 400 "JSON aninhado demais" e deixa uma linha de aviso no log.
- **Webhook: `minutes` traz só o tempo de quem é dono do webhook.** Numa tarefa transferida pelo admin, o campo somava também as horas de quem tinha a tarefa antes (que o app e a API não mostram ao novo dono). Agora bate com o que a pessoa vê na tarefa.
- **Logo: WebP de formato desconhecido é recusado.** Um arquivo com cabeçalho de WebP mas sem ser de um dos três formatos (VP8, VP8L, VP8X) passava sem conferência de tamanho; agora o envio responde 400 com a explicação.

## Mudanças de resposta de API (docs/API.md e openapi)

- Qualquer rota com corpo JSON: corpo com aninhamento que estoura a pilha do servidor (na prática, de ~1.000 a ~5.000 níveis; acima disso o parser já recusava) responde **400** `{"detail": "JSON aninhado demais"}` em vez de 500. Até ~900 níveis segue o 422 de sempre; ~20.000 segue `400 "There was an error parsing the body"` (não mudou). O `/mcp` não foi tocado (já tratava).
- Webhook, eventos de tarefa: `data.minutes` passa a ser a soma dos apontamentos **do dono do webhook** naquela tarefa (antes: de todos). Nome do campo igual; só muda o valor em tarefa transferida com horas de quem saiu.
- `POST /api/admin/branding/logo`: WebP cujo primeiro bloco não é `VP8 `, `VP8L` ou `VP8X` responde **400** `"WebP de formato desconhecido; exporte a imagem de novo"` (antes: 200).
- `GET /api/search?q=...%00...`: já respondia **400** (handler de DataError do p10); só ganhou teste. `GET /api/search/similar?title=...%00...` responde 200 (o NUL é descartado como separador de palavras, não chega ao banco).

## O que NÃO foi feito

- **Limite de lado para logo SVG**: não feito. O teste antigo `tests/test_aud_p10.py::test_logo_com_lado_gigante_e_recusado` fixa que um SVG com `width="99999" height="99999"` é aceito (200, "segue como antes"); mudar isso exigiria alterar teste antigo.
- WebP dos formatos conhecidos mas com cabeçalho truncado ou assinatura interna errada (ex.: `VP8 ` sem os bytes `9d 01 2a`, `VP8L` sem `0x2f`, arquivo com menos de 30 bytes) continua aceito sem conferência de lado, como o PNG sem IHDR. O item pedia só a recusa do formato desconhecido.
- `search.py` não foi alterado (não precisou).

## O que não foi verificado

- O handler geral de `RecursionError` responde "JSON aninhado demais" para qualquer RecursionError que escape de uma rota; se um dia houver recursão infinita em código nosso, ela sairá como 400 com a linha de aviso no log, não como 500 com a pilha. Não achei caso assim hoje, mas não varri todas as rotas.
- O limite exato em que o 422 vira 400 depende da pilha do Python (hoje entre 900 e 1.100 níveis); testado só em 900, 1.100, 2.000, 5.000 e 20.000 em `/api/auth/login` (anônimo) e `/api/worklog` (com sessão), mais um objeto de 3.000 níveis dentro de `description`. Outras rotas não foram exercitadas uma a uma.
- A entrega real do webhook (HTTP para um destino de verdade) não foi feita no ambiente a02; a prova é pela suíte (`payload` e `run_once` com destino falso).
- Nenhuma tela mudou: não houve conferência com Playwright nem `node --check` (nenhum .js tocado).
