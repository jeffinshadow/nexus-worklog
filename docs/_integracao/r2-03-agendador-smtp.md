# r2-03-agendador-smtp: nota para o integrador

## O que está neste branch (lab/r2-03-agendador-smtp)

Só o item 3 (marcador da passada). Os itens 1, 2 e 4 **não entraram**: ver "O que NÃO foi feito".

### CHANGELOG (pronto para colar)

- Saúde do Nexus: "agendador parado" não acende mais em falso quando uma passada demora (servidor de e-mail lento, muitas pessoas). O sinal de vida do agendador passa a andar no começo da passada, entre os serviços e a cada pessoa do envio de e-mail.

### API

- `GET /api/admin/health`: `scheduler_last_pass` mantém nome e tipo; o sentido passa de "fim da última passada" para "último sinal de vida do agendador" (começo/fim da passada, entre os serviços, a cada pessoa do e-mail). O limite de 5 min da tela não mudou. Sem mudança no openapi.

## O que NÃO foi feito (e por quê)

- **Itens 1, 2 e 4 (espera crescente do SMTP, log, "e-mail suspenso até HH:MM" na Saúde)**: um teste antigo fixa o comportamento que o item 1 muda, e a regra do pacote manda parar e registrar. É `backend/tests/test_aud_p12.py::test_smtp_que_recusa_a_conexao_tenta_de_novo_na_proxima_passada`: falha às 8h01 e exige `sent` às 8h02; com a 1ª espera de 2 min pedida pelo pacote, a nova tentativa só sai às 8h03.
- **Proposta pronta, fora deste branch**: `lab/r2-03-agendador-smtp-disjuntor` (neste mesmo clone, 3 commits em cima deste branch: `40895c5`, `570f243`, `e7331ed`) implementa os itens 1, 2, 4 e os testes do item 5. Para aceitar, é preciso mudar **uma linha** do teste antigo (não mudei): em `test_aud_p12.py`, `notify.run_once(em(8, 2))` vira `notify.run_once(em(8, 4))` (linha 94). Com essa linha, os três arquivos (`test_r2_03.py`, `test_aud_p12.py`, `test_aud_p07.py`) passam (34 testes); sem ela, a suíte inteira dá 811 passam e 2 falham, as duas em `test_aud_p12.py` (a citada e a seguinte, `test_smtp_que_aceita_e_depois_falha_nao_reenvia`, que herda o disjuntor aberto pela primeira no mesmo processo).
  - O que a proposta faz: `notify.smtp_down = {"failures", "until"}` na memória do processo; `MailNotSent` suspende o envio de todos por 2, 5, 10 e 15 min (teto); suspenso, `run_once` nem consulta as pessoas, nem chama `_claim`, nem monta; `sent` zera. Senha recusada (`MailError`) segue erro do dia e não mexe no disjuntor. Janela de 2 h intacta. Uma linha de log a cada suspensão (com os minutos) e uma na volta; a linha por pessoa saiu do `deliver`.
  - CHANGELOG da proposta: "Servidor de e-mail fora do ar: o Nexus para de remontar o aviso de cada pessoa a cada minuto e tenta de novo depois de 2, 5, 10 e então a cada 15 min, até 2 h depois da hora do aviso. A Saúde do Nexus mostra 'e-mail suspenso até HH:MM depois de N falhas de conexão'."
  - API da proposta: `GET /api/admin/health` ganha `email.suspended`: `null` ou `{until: data-hora UTC, failures: inteiro}` enquanto o envio está suspenso (campo único e novo; o resto do bloco não muda).
  - Limites conhecidos da proposta: o estado zera ao reiniciar o backend; convites e links de senha (fora do agendador) não abrem nem fecham o disjuntor; o log de suspensão usa `mailer.last["error"]` como motivo.

## O que não foi verificado

- Neste branch não há mudança de tela nem de JS: nada conferido no navegador.
- O marcador a cada pessoa foi testado com `_user_pass` falso, não com um SMTP de verdade pendurado por minutos.
- Da proposta (branch do disjuntor), conferido no a03 com o Mailpit parado e 5 pessoas com aviso na hora: uma linha "SMTP fora do ar (1 falha de conexão) ... nova tentativa em 2 min" às 14:17:00, nenhuma reserva em `notification_log`, a Saúde (1440 e 390 px, sem erro de console, sem rolagem lateral) com "e-mail suspenso até 14:15 depois de 1 falha de conexão" em tom de alerta; com o Mailpit de volta, "SMTP voltou" às 14:19:00 e os 5 avisos entregues uma vez. `node --check` em `saude.js` passou.
- Da proposta, NÃO conferido em tempo real: a sequência 5/10/15 min (só nos testes, com o relógio adiantado), SMTP que pendura em vez de recusar, TLS quebrado, o resumo de segunda com PDF e o texto no plural ("N falhas") na tela.
