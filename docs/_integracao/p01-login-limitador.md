# p01-login-limitador — notas para a integração

Branch `lab/p01-login-limitador`. Testes novos em `backend/tests/test_aud_p01.py`.

## Linhas para o CHANGELOG

Segurança
- Tela de login: tocar em "Entrar" (ou dar Enter) antes de a página terminar de carregar não manda mais e-mail e senha
  na URL. Os quatro formulários da tela usam `method="post"` e o botão de envio só liga quando o `login.js` carregou.
- Admin inicial: o Nexus só cria o admin do `.env` (`ADMIN_EMAIL` + `ADMIN_INITIAL_PASSWORD`) quando não existe
  nenhuma conta admin. Antes, trocar o e-mail do admin ou excluir a conta fazia nascer, na subida seguinte, um admin
  novo com a senha inicial do `.env`.
- Limite de tentativas: com o limitador cheio (10 mil chaves), saem as chaves que ainda não estouraram e ficam as
  bloqueadas; ninguém é recusado só porque o limitador encheu (antes, 10 mil pedidos trancavam o login de todos por
  5 minutos).
- "Sair dos outros aparelhos" desliga as notificações de todos os aparelhos da conta (este se inscreve de novo ao abrir
  o app). `POST /api/auth/logout` aceita `{"endpoint": "..."}` (opcional) e apaga essa inscrição.
- Senhas fáceis de adivinhar são recusadas no convite, na troca e na redefinição: igual ao e-mail da conta, um
  caractere só repetido, só dígitos em sequência ou repetição (1234567890, 0000000000, 1212121212) e só "nexus"
  repetido. Mensagem: "Essa senha é fácil de adivinhar."
- "Esqueci a senha" responde antes de consultar a conta (o tempo de resposta não diz mais quem tem conta).

Correções
- Entrar com a senha certa (ou com a passkey) não gasta mais o limite por IP: por IP contam só as falhas (10 em
  5 minutos). Abrir a tela de login também não gasta (o pedido da passkey tem limite próprio, 60 em 5 minutos). Os
  limites por e-mail (100 falhas) e por e-mail+IP (10 falhas) não mudaram.
- O 429 do login diz quanto falta: `Retry-After` com os segundos de verdade e a frase "Muitas tentativas. Espere N
  minutos."
- Conta bloqueada que usa "Esqueci a senha" recebe um e-mail curto dizendo que o acesso está bloqueado por quem
  administra (a tela responde igual; mesmos limites).
- Sessão vencida: com `?motivo=sessao` na URL, o login mostra "Sua sessão terminou (ela vale 7 dias). Entre de novo
  para continuar de onde parou."
- Convite vencido: título "Convite vencido" e, com e-mail no servidor, a frase aponta o "Esqueci a senha".
- Tela de login com `<main>` (leitor de tela).
- Dias úteis: dois pedidos iguais ao mesmo tempo não congelam as rotinas duas vezes (`FOR UPDATE` na linha da conta).

## O que o integrador precisa saber

- **openapi**: `POST /api/auth/logout` ganhou corpo opcional (`LogoutIn.endpoint`). `test_openapi_em_dia` falha até
  regerar `docs/openapi.json`.
- **conftest.py** (não editei): falta `security.passkey_options_limiter` na lista de limitadores zerados a cada teste.
  Hoje não faz falta (a suíte chama `/passkeys/login/options` poucas vezes por processo e o teto é 60), e
  `test_aud_p01.py` zera o seu por conta própria; convém acrescentar.
- **test_revisao.py** (editei UMA asserção, fora da lista de arquivos do pacote):
  `test_ip_v6_agrupa_por_64_e_limitador_cheio_recusa_novas` afirmava o comportamento antigo (cheio recusa chave nova),
  que este pacote muda de propósito. Virou `..._nao_recusa_novas` e afirma que a chave nova passa.
- **Decisão da R3 revista**: a R3 decidiu "limitador cheio recusa chave nova (não zera)". Mantive o "não zera" para
  quem já estourou (o bloqueio de quem errou 10 vezes continua) e troquei o "recusa" por descartar as chaves que não
  estouraram. Risco conferido pelo revisor do pentest: o teto por e-mail fica em outro dicionário
  (`login_email_limiter`), então o descarte não reabre força bruta numa conta; o que se perde, com o limitador cheio, é
  a contagem parcial (menos de 10) de quem ainda não tinha estourado.
- **ADMIN_EMAIL deixa de recriar o admin**: quem contava com "mudei o ADMIN_EMAIL no .env e subi de novo" para
  recuperar o acesso não tem mais esse caminho enquanto existir alguma conta admin (mesmo bloqueada). O p06 escreve no
  `docs/ADMIN.md` a recuperação por psql.
- **Mensagem do 429**: a frase "Muitas tentativas. Espere N minutos." vem pronta do servidor no `detail` (o `api.js`,
  que não é deste pacote, não entrega cabeçalhos ao `login.js`; o `login.js` já mostra o `detail`). O `Retry-After`
  vai junto para automações. Vale para o login por senha, por passkey e para `/passkeys/login/options`. Os outros 429
  da tela (links, esqueci a senha, pedido de convite) seguem com o texto e o `Retry-After: 60` de antes.
- **Front do "Sair"** (mandar o `endpoint` no logout) é do p11; **`?motivo=sessao`** quem envia é o p04.
- **`?v=166`** em `login.html` não foi mexido (versão é do integrador): o `login.js` mudou e precisa do número novo
  para o navegador não usar o antigo em cache. Atenção: HTML novo com `login.js` antigo em cache deixaria os botões
  desligados.
- **Passkey**: falha de login por passkey passou a contar no limite por IP (antes toda tentativa contava). Desafio
  vencido ou inexistente (400) não conta.

## O que ficou de fora e por quê

- Lista embutida de senhas comuns, pedir senha ao cadastrar passkey, validade da senha temporária, botão "mostrar
  senha": fora por decisão do pacote.
- `routers/invite_requests.py` (tempo de resposta do pedido de convite) e a faxina do login (`auth.py`): são do p12.
- Botão "Mandar um link novo para o meu e-mail" na tela de convite vencido: o pacote pediu só a frase.
- Concorrência #4: feita só a metade pedida (`FOR UPDATE` e saída antecipada em `save_settings`); sem teste com duas
  conexões ao mesmo tempo, só o de pedido repetido.
