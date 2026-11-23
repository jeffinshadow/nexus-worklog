# p11-sw-boot-appjs: service worker, abertura do app e app.js

Branch `lab/p11-sw-boot-appjs`. Arquivos: `web/static/sw.js`, `js/app.js`, `js/fila.js` (só `wipe()`),
`js/notificacoes.js`, `index.html` (uma linha) e o novo `js/abertura.js`.

## Linhas para o CHANGELOG

- Sem sinal: o primeiro acesso no aparelho (ou a troca de conta) não apaga mais os arquivos do app que acabaram de ser
  guardados; o app reabre sem sinal já depois do primeiro login. O Sair continua apagando a fila e as leituras, e passa
  a manter só os arquivos do app (nada da conta).
- Servidor reiniciando (502, 503, 504): o app abre com a cópia guardada, como sem rede, em vez de mostrar erro.
- Sinal fraco (o aparelho diz que tem rede, mas nada responde): depois da primeira espera estourada, a página e as
  leituras esperam a rede só 1,5 s durante 60 s, e o resto do app vem da cópia guardada nessa abertura. Reabrir cai de
  mais de 20 s para poucos segundos. Com rede boa nada muda: rede primeiro.
- Projeto já visitado abre sem sinal (`/api/projects/N/overview` entra nas leituras guardadas).
- "Abrindo o Nexus…" não fica mais para sempre quando um arquivo do app não chega: aparece "Não abriu" com
  "Tentar de novo".
- Configurações não fica mais carregando quando o service worker não registrou (segue depois de 3 s, com
  "Desligadas neste aparelho").
- Erro do próprio app ao montar uma tela agora vai para o log do servidor (`/api/client-errors`); sessão vencida não.
- Voltar do aparelho (ou um link) com uma janela aberta fecha a janela antes de trocar de tela.
- Sair cancela as notificações deste aparelho e manda o endereço da inscrição no corpo do logout.
- Busca lateral: o leitor de tela ouve quantas sugestões apareceram, e o campo informa aberto/fechado
  (`aria-expanded`).
- Ajuda: uma linha sobre a Revisão da semana.

## Para o integrador

- **Arquivo novo** `web/static/js/abertura.js` (script comum, carregado no `<head>` antes dos módulos, por causa da
  CSP `script-src 'self'`). Não está na lista de arquivos do pacote, mas o item pede "arquivo próprio em /js/".
- **Depende do p01**: o `POST /api/auth/logout` passa a receber `{"endpoint": "..."}` quando o aparelho tem
  notificações ligadas. Sem o p01 o servidor ignora o corpo e nada quebra (a inscrição do navegador é cancelada de
  qualquer jeito).
- **Depende do p15**: a linha da Ajuda diz que a Revisão da semana "abre pela Passagem de turno, no Hoje; no celular,
  também em Mais". Se o p15 não entrar, ajustar o texto (`app.js`, `showHelp`).
- **Além do que o item 1 pedia**: logo depois do `wipe()` da troca de conta, o `boot()` pede `/auth/me` e a identidade
  visual de novo, só para ficarem guardados. Sem isso o casco ficava, mas o app ainda não reabria sem sinal no primeiro
  login, porque a leitura da conta saía junto com `nexus-dados`.
- `?v=166` e `dropOldVersions` intocados (o `abertura.js` usa o mesmo `?v=166`).
- Sem teste automatizado no repositório: o pacote proíbe mexer em `backend/tests/` e o front não tem suíte. As provas
  foram roteiros de Playwright fora do repositório (ver "Como foi conferido").

## Decisões que merecem um olhar do dono

- **"Rede primeiro, sempre" virou "rede primeiro" com duas exceções** (cabeçalho do `sw.js`). A espera curta só liga
  depois de um estouro de tempo de verdade (erro rápido, como modo avião ou 502, não liga) e desliga na primeira
  resposta do servidor. O resto do casco (CSS, JS, fontes) nunca usa a espera curta: ou vem todo da rede (página veio
  da rede) ou todo da cópia (página veio da cópia), para não misturar módulos novos e velhos depois de um deploy.
- **Voltar fecha a janela e também troca de tela** (o mínimo aceito pelo revisor; sem `pushState`). O que estava
  digitado na janela se perde, como já acontecia com o Esc. Ficam de fora o detalhe lateral (é da rota) e o tour.
- **`aria-expanded` no campo de busca** foi posto como o item pede, com `aria-controls`. O campo continua
  `type="search"` (não virou `combobox`); um validador estrito pode reclamar do atributo nesse papel.

## Como foi conferido

Roteiros de Playwright (Chromium, 390 px e 1280 px) contra o a11, fora do repositório, adaptados dos relatórios
`mobile-pwa` e `frontend-codigo`. Resultado na versão final: 21/21, 11/11 e 7/7.

- Primeiro login: casco com 49 arquivos; recarregar sem rede abre (390 e 1280 px).
- Backend parado (502 real do nginx): reabre da cópia; com o backend de volta, abre da rede.
- Proxy "buraco": 1ª abertura 13,8 s (paga um estouro de 10 s), 2ª e 3ª em 5,3 s, sem nenhum JS/CSS pedido à rede.
  Rede de volta: 1,1 s, da rede. Erro rápido (modo avião) não liga a espera curta. Rede lenta mas viva (2,5 s) depois
  do buraco: passados os 60 s volta a valer a rede (não fica presa na cópia).
- Módulo abortado: "Não abriu" com "Tentar de novo", que recarrega e abre; rede lenta (250 ms por arquivo) sem aviso
  em falso.
- `sw.js` abortado: Configurações carrega em 3,3 s com "Desligadas neste aparelho".
- Erro forçado no Hoje: 1 POST em `/api/client-errors`; sessão vencida (401): 0.
- Voltar com a Nova tarefa aberta e com janela sobre janela: fecham; `#/tarefas?id=N` abre o detalhe e ele fica.
- Sair: com inscrição push simulada, o POST leva o endpoint e `unsubscribe()` é chamado; o casco fica e as leituras
  saem. Sem rede e sem permissão de push, sai em 1,4 s.
- Suíte do backend inteira (`lab.sh test 11`): 592 passaram, 1 pulado.

## Não verificado / pendências

- **Push de verdade**: o Chromium do laboratório não assina push; a inscrição foi simulada. Falta conferir num
  aparelho que o Sair desliga a notificação, e junto com o p01 que o servidor apaga a inscrição pelo endpoint.
- **Safari/iPhone e Firefox**: nada foi visto fora do Chromium. O "resto do casco vem da cópia" depende de
  `resultingClientId`; num navegador sem ele, a página ainda ganha a espera curta, mas cada arquivo volta a esperar
  10 s (como hoje).
- **Service worker reiniciado pelo navegador** perde as duas marcas (são variáveis de módulo): a espera volta ao
  normal e a abertura em curso volta a ser rede primeiro. Não foi provocado em teste.
- Em sinal fraco contínuo, a cada 60 s um pedido paga a espera cheia de novo (é o que impede a rede lenta de ficar
  presa na cópia).
- Com o backend parado, reabrir levou 6,5 s (a página vem da rede, as leituras da cópia); não investiguei onde o tempo
  vai, nem a observação do revisor do frontend-codigo ("Não foi possível carregar" 12 s depois).
- O rascunho da Nova tarefa ao voltar (mobile-pwa #9) não é deste pacote: o Voltar fecha a janela e o texto se perde.
