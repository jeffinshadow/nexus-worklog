# r2-10-infra-vigia-deploy: nota para a integração

Branch `lab/r2-10-infra-vigia-deploy`, a partir de `lab/integracao` (3694956). Arquivos tocados: `deploy.sh`,
`tools/vigia.sh`, `backend/tests/test_r2_10.py` e esta nota. `web/nginx.conf` não mudou (ver "Não feito").

## Linhas para o CHANGELOG

- **Vigia sem alarme falso na atualização.** Enquanto o `./deploy.sh` roda, o vigia de saúde não reinicia nada nem
  manda e-mail: acabou o par "/api/health sem resposta" e "tudo saudável de novo" a cada atualização mais demorada.
  Se o deploy falhar ou terminar, o vigia volta a olhar na passada seguinte; se o deploy morrer no meio, volta em
  15 minutos.
- **Senha do banco com caractere especial.** O `./deploy.sh` agora aceita senha com `/ @ # ? %` ou espaço, desde que
  a `POSTGRES_PASSWORD` leve a senha como ela é e a `DATABASE_URL` leve a mesma senha codificada (`@` vira `%40` etc.).
  Quando as duas não batem, a mensagem diz qual forma vai em cada variável. Continua mais simples usar só letras e
  números (`openssl rand -hex 24`).
- **Aviso do vigia mais claro** quando os três containers estão rodando e a aplicação não responde: o e-mail não manda
  mais "subir o que está parado" (não há nada parado). A passada também ficou 10 s mais curta nesse caso.
- Um `.env` sem `POSTGRES_PASSWORD` não faz mais o `./deploy.sh` sair calado, sem mensagem.

## Mudanças de API

Nenhuma (nada no backend, no `docs/API.md` nem no openapi).

## O que mudou, por item

1. **Marcador do deploy** (e294844). `deploy.sh` grava `estado/deploy-em-andamento` no começo do passo 5 (depois do
   backup; o `--backup` do cron nunca grava nem apaga) e de novo logo antes do `docker compose up -d`, com
   `trap ... EXIT` para apagar em qualquer saída. `tools/vigia.sh` sai no começo da passada se o marcador tem menos de
   15 min (`find -mmin -15`) e confere de novo antes de agir (passada que começou segundos antes do deploy). A pasta
   `estado/` já é ignorada pelo git e o backend só lê `backup.json` e `deploy.json` dela.
2. **Trava da senha** (9458e5b). Só age quando a `POSTGRES_PASSWORD` tem caractere reservado. Tira a senha da
   `DATABASE_URL` (entre o primeiro `:` depois de `//` e o último `@`), decodifica os `%XX` e compara com a
   `POSTGRES_PASSWORD` crua. Recusa se a senha da URL tem `/ @ # ?` ou espaço crus, ou se a decodificada é diferente.
3. **Ramo "aplicação sem resposta com tudo running"** (93115e3). Rodado de verdade no a10 (ver "Verificado"). O ramo
   funciona; apareceram duas coisas pequenas, corrigidas: o e-mail dizia "serviço parado não é religado pelo vigia:
   docker compose up -d" sem haver serviço parado, e as "três tentativas em 20 s" levavam 30 s (dormia 10 s depois da
   última).
4. **nginx**: nada a mudar, ver abaixo.
5. **Testes**: `backend/tests/test_r2_10.py`, 11 casos por subprocesso com `docker`, `git`, `logger` e `sleep` falsos.

## Pendente para quem integra (fora dos meus arquivos)

- **`docker-compose.test.yml`: os testes novos ficam PULADOS na suíte até montar os scripts.** O container de testes
  só enxerga `backend/`. Acrescentar em `tests.volumes`:

      - ./deploy.sh:/deploy.sh:ro
      - ./tools:/tools:ro

  Com esses dois volumes (passados com `-v` no `docker compose run`) os 11 passam; contra os scripts de 3694956,
  8 falham (os 3 que passam são os casos "aceita" da senha, que já eram aceitos antes).
- **Documentação da senha**: `README.md:316`, `docs/ADMIN.md:54` e `docs/ADMIN.md:381` dizem para usar só letras e
  números. Continua certo como recomendação; quem quiser pode citar a forma codificada. Não editei.
- **`docs/ADMIN.md`, seção 8 (vigia)**: vale uma frase dizendo que o vigia fica calado durante o `./deploy.sh`.

## Não feito

- **`web/nginx.conf` (error_log com a query string)**: as duas rotas com segredo na URL (`= /api/auth/link` e
  `^~ /api/calendar/`) já têm location próprio com `access_log off` e `error_log /dev/null`, que é mais forte que
  subir o nível para `crit`. Conferi no a10 com o backend parado: os pedidos a essas duas rotas deram 502 e não
  deixaram linha nenhuma no log do `web`. O que continua indo para o error_log é a query das outras rotas da API
  (ex.: `GET /api/worklog?q=...`) quando o upstream falha. Calar isso exigiria `error_log ... crit` no `location /api/`
  inteiro, e aí a operação perde justamente as linhas "connect() failed / could not be resolved" que explicam um 502.
  Julguei arriscado e não fiz.
- **Comportamento novo da trava a saber**: com caractere reservado na `POSTGRES_PASSWORD`, a trava agora recusa
  também quando a senha da `DATABASE_URL` é simplesmente outra (antes só recusava a senha crua repetida na URL).
  Quem trocou a senha no banco com `ALTER USER` (seção 13) e deixou a `POSTGRES_PASSWORD` antiga, com caractere
  reservado, no `.env` passa a ser barrado no deploy até igualar as duas. Senha só com letras e números não é
  conferida, como antes.

## Verificado

- shellcheck (`koalaman/shellcheck:stable -x`) nos dois scripts: zero avisos.
- Vigia de verdade no a10 (containers reais, e-mail real no Mailpit, `logger` falso, ambiente mínimo `env -i`, `docker`
  embrulhado só para trocar o health por uma porta fechada): saudável = silêncio; health fechado com tudo running =
  um e-mail "serviço com problema (aplicação(/api/health sem resposta))" e `.vigia-alerta`; segunda passada não
  repete; com marcador novo = silêncio e sem `.vigia-alerta`; com marcador de 16 min = avisa; health de volta =
  "tudo saudável de novo" e estado apagado. Passada doente: 22 s depois da correção (antes 32 s).
- libpq (`psycopg.conninfo.conninfo_to_dict` na imagem de testes): `xy%40zw` na URL vira a senha `xy@zw`; `xy%zw` dá
  "invalid percent-encoded token"; `xy@zw` e `xy/zw` crus cortam o host. É o mesmo critério da trava. Não subi um banco
  de verdade com senha assim.
- Suíte inteira (`lab.sh test 10`): 806 passaram, 11 pulados (os deste pacote, pelo motivo acima); com os dois
  volumes, `tests/test_r2_10.py` sozinho: 11 passaram.

## Não verificado

- `./deploy.sh` de ponta a ponta com docker de verdade (o marcador foi provado só com `docker` e `git` falsos, no
  teste): não medi uma atualização real com o timer do vigia rodando ao lado.
- O timer do systemd (`nexus-vigia.timer`) e o `logger` de verdade no journal.
- Backend respondendo 502 de verdade (processo morto dentro do container com o container ainda `running`): simulei
  pela porta fechada; para o vigia os dois casos são o mesmo `wget` com saída diferente de zero.
- Saída do `deploy.sh` por sinal (Ctrl+C, kill): o `trap EXIT` do bash cobre, mas não testei. Com `kill -9` o
  marcador fica e o vigia volta a avisar em 15 min, como previsto.
- Deploy cujo `up` e teste de fumaça passem de 15 min: o vigia voltaria a avisar no meio.
