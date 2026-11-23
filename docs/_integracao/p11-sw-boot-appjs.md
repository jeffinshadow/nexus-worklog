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
