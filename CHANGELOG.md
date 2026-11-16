# Histórico de versões

Nexus Worklog segue [SemVer](https://semver.org/lang/pt-BR/): **MAJOR** = quebra de API/MCP ou
reforma profunda de como o app é usado; **MINOR** = recurso novo; **PATCH** = correção.
Quebras só em versão maior; rota ou campo antigo continua funcionando, marcado como obsoleto, até a
maior seguinte (política completa em [`docs/ADMIN.md`](docs/ADMIN.md#versionamento-e-compatibilidade) e
[`docs/API.md`](docs/API.md#versões-e-compatibilidade)). A versão atual fica em
`backend/app/version.py` (também no MCP e no `docs/openapi.json`). Datas marcadas com ~ são a do commit,
não a da hora do deploy. As versões 0.x e 1.x foram numeradas depois, sobre o histórico do git
(etiquetas `v0.1.0` … `v1.12.1`).

## 2.1.0 — 2026-11-16

Rodada de robustez ("gauntlet loop"): pontos frágeis achados na leitura do código, sem mudar como o app é usado.

### Mudou de regra (decisão do dono, 16/11)
- **Rotina "N dias depois da última vez"**: uma pausa que terminou empurra o vencimento para o dia da volta (quem
  volta de férias tem o ciclo inteiro para fazer; antes levava falta no primeiro dia), e a rotina que acabou de trocar
  de agenda não vence antes do dia da troca (antes podia nascer com falta nesse mesmo dia, "atrasada desde ontem").
  Os números de períodos passados de rotinas desse tipo que tiveram pausa ou troca podem mudar.
- **Primeiro amanhã**: a escolha de um dia que já passou só continua valendo se a pessoa não usou o Nexus desde então
  (feriado, folga). Quem abriu o app no dia e não fez a tarefa não fica mais com o selo "primeiro hoje" por até 7
  dias. `PUT /api/board/first` com `day` = hoje e a lista vazia tira o selo de hoje.

### Tudo ou nada
- **Transações** (`db.transaction()`): criar, editar, concluir, excluir e atribuir tarefa, excluir projeto ou objetivo,
  trocar a agenda de uma rotina, mudar os dias úteis e **desfazer** gravam a mudança e a linha do histórico juntas. Antes,
  cada comando gravava sozinho: uma falha no meio deixava a tarefa excluída sem a cópia para o desfazer, ou o desfazer
  pela metade (tarefa de volta sem as anotações).
- Dois "Desfazer" da mesma ação ao mesmo tempo: o segundo responde 409 e não repete nada.

### Correções
- **Exportar tudo (JSON)** dava erro para quem teve tarefas transferidas a outra pessoa e continuou com a conta. O tempo
  apontado nessas tarefas agora vai em `time_on_transferred_tasks` (campo novo).
- Título, anotação, item de checklist e nome de rotina **só com espaços** são recusados (422); anotação e item em branco
  davam erro 500. Os espaços das pontas saem.
- **MCP**: `params` que não é objeto (ou `name` que não é texto) devolve o erro `-32602` do protocolo, não mais 500.
- **Passkey**: conta bloqueada não entra, mesmo que uma passkey tenha sobrado (403, como no login por senha).
- Excluir de novo uma rotina já excluída não grava outra linha no histórico; convite repetido ao mesmo tempo responde
  409 em vez de 500.
- Histórico: cadastrar ou remover passkey e convidar ou recusar um pedido de convite aparecem com frase, não com o nome
  interno da ação.
- App: o detalhe da tarefa aberto sem sinal mostrava "Invalid Date"; depois de adicionar um item, o foco volta ao campo
  "Adicionar item"; "Concluir" na revisão da semana não trava se o servidor recusar; "foto grande demais" aparece com
  essa frase; o aviso "daqui a pouco" de uma rotina fechado com Ok volta no dia seguinte (com o app aberto de um dia
  para o outro, ficava calado); dois toques em "Anotar" ou em "Marcar como aguardando" não gravam duas vezes; o Hoje
  não aparece em dobro quando duas atualizações se cruzam; trocar de aba no Admin antes de a anterior carregar não
  mistura as duas, e uma aba que falha ao carregar mostra a frase em vez de ficar em branco.
- `deploy.sh`: se o `git pull` ou o `docker compose up` falhar, o script diz o que aconteceu e como voltar atrás (saía
  sem as instruções); backup recusado na conferência não fica na pasta.

### Privacidade e permissões
- **Sair sem conexão** não encerrava a sessão no servidor: quem abrisse o app depois, no mesmo aparelho, entrava na
  conta. Agora a saída fica anotada e a sessão é encerrada na primeira abertura com rede, antes de mostrar qualquer coisa.
- Quem acompanha a equipe não recebe mais, na API, o ranking por rotina (com a sequência de dias) nem o backlog por
  idade da pessoa: a tela já não mostrava; a resposta ainda trazia.
- **Vencimento compartilhado** deixa de aparecer para a equipe quando quem criou sai dela. Editar ou excluir o
  vencimento de um colega como admin vale só pelo app, não por chave de API.
- Conta bloqueada ou com convite pendente fica fora do CSV de horas da equipe e das fotos, como já ficava do painel.

### Privacidade e permissões (contas e links)
- **Senha nova invalida os links antigos**: o pedido de troca de e-mail, o link de nova senha e o convite deixam de
  valer quando a senha é trocada ou redefinida. Antes, quem tinha a senha antiga podia pedir a troca de e-mail, esperar
  a dona trocar a senha e ainda confirmar o link, ficando com a conta.
- Convite antigo não cria mais a senha depois de um "Redefinir senha" nem depois de o admin corrigir o e-mail da conta.
- **Passkey nova avisa por e-mail** (ela entra sem senha e continua valendo depois de uma troca de senha).
- Outro admin não altera nenhum papel do admin master; o código de transferência do master conta a tentativa antes de
  comparar (pedidos em paralelo não passam das 5).
- Tarefas transferidas pelo admin ficam também no histórico de quem as tinha (quantas e para quem).
- Ao sair, o cookie de sessão é apagado de verdade (o `__Host-` exigia os mesmos atributos); o link de convite ou de
  senha não é gasto quando o servidor está ocupado; o push não segue redirecionamento; e-mails não vão mais em claro
  para o log.

### IA (MCP)
- `stop_timer` e `start_timer` com um cronômetro esquecido (mais de 12 h) davam erro 500 depois de já terem parado o
  cronômetro.
- Título de objetivo ou nome de projeto só com espaços, datas absurdas e `arguments` de prompt fora do formato viram
  erro claro, não 500.
- `external_ref` já usado em OUTRA tarefa (em `log_time` e `add_note`) é erro, dizendo em qual tarefa está: a resposta
  dizia "já apontado" na tarefa pedida, que ficava sem o tempo.
- O prefixo do id vale só no campo dele: `task_id: "R7"` não conclui mais a tarefa #7 (a IA queria a rotina R7).
- `list_tasks` com `status: all` continua nas concluídas além das 200 mais recentes; com período, `status` e `by`
  inválidos são recusados; projeto com nome só de números é achado pelo nome.
- `set_recurring` que pausa e não consegue marcar diz as duas coisas; `update_objective` confere a posição antes de
  gravar o título.
- Vencimento da equipe cadastrado por outra pessoa, o título de tarefa atribuída no cronômetro e nas "escolhidas para
  hoje" e o motivo de devolução no histórico vão entre « » (texto de terceiro).

### Correções (áreas revisadas pelos críticos)
- Prazo, dia de cobrar e vencimento aceitam datas de 2000 a 2100. Uma data como 9999-12-31 ("nunca vence") ou o ano 1
  derrubava o calendário (ICS), a lista de vencimentos, a passagem de turno e o e-mail da manhã, inclusive os de quem
  divide a equipe; as que já estiverem gravadas não derrubam mais nada.
- **Cronômetro**: parar ou trocar de tarefa é tudo ou nada (uma falha ao apontar não some mais com o cronômetro e o
  tempo); dois aparelhos iniciando ao mesmo tempo não dão erro.
- Painel e Meu mês com mês de ano inválido (`month=0001-01`) respondem 400, não 500.
- **Sem sinal**: tarefa criada sem conexão aparece em Tarefas só com o título e "esperando conexão" (com as ações, o
  cronômetro iniciado nela era recusado depois e o tempo se perdia); o texto digitado no detalhe não some quando o
  salvamento falha por falta de rede; "+ Tarefa" no projeto e "Virar tarefa" nos vencimentos dizem que a tarefa ficou
  guardada, sem erro falso nem duplicação; foto que não abre não segura a tarefa compartilhada; Tarefas e Projetos
  abrem sem sinal mesmo sem terem sido visitadas antes.
- "Antes do PDF" não aponta o tempo duas vezes quando o "como resolveu" falha; o lembrete de inatividade não cria duas
  tarefas com dois toques; a busca não mostra dois blocos de resultado; o título de um projeto não aparece em outra
  tela; a Equipe de quem não está em nenhuma equipe não dá erro falso; as notificações bloqueadas explicam como liberar;
  a hora do cronômetro esquecido segue o fuso da app.

### Relatórios
- Tempo apontado numa tarefa que depois foi transferida a outra pessoa: aparecia em dobro em "sem projeto" no painel
  e, no PDF e em Meu mês de quem apontou, também sob um projeto de quem recebeu. Agora conta uma vez, sem projeto.
- Texto do período (PDF e e-mail da semana): "Foi feita 1 de 1 rotina prevista", "Fica 1 tarefa em aberto"; a
  porcentagem só chega a 100% com tudo feito e só fica em 0% sem nada (199 de 200 saía "100%").
- Diário do PDF: o apontamento de uma tarefa aberta não some mais quando outra tarefa de mesmo título foi concluída
  no dia.
- IA: o título de tarefa atribuída também vai entre « » em `list_objectives`, `get_week_review` e nas respostas do
  cronômetro.
- Índice para a lista de projetos (`sql/045`): lia os objetivos de todas as contas.

### Novo
- `GET /api/worklog?project=<id>`: a lista por período só com as tarefas do projeto (principal ou extra). A ferramenta
  `list_tasks` da IA usa o mesmo filtro: num período com mais de 500 tarefas, as do projeto podiam ficar de fora.

### Desempenho
- A lista de tarefas por período compara os dias pelo índice de datas.
- Histórico: "pode desfazer" é calculado só para as linhas da página, pelo índice (ordenava o histórico inteiro da
  pessoa a cada página, a cada Desfazer e a cada aviso com Desfazer).
- Contas (Admin), Equipe e Atribuir leem os perfis numa consulta só (era uma por pessoa; no Atribuir, três).
- Reordenar rotinas e objetivos é um comando só.
- O app instalado descarta a cópia da versão anterior dos arquivos ao guardar a nova.
- Notificações da manhã leem só os prazos e as cobranças (liam o quadro inteiro a cada minuto, por duas horas, por
  pessoa); os avisos de agenda conferem antes de gravar (regravavam a cada minuto e gastavam ids do histórico).
- Os webhooks são entregues em laço próprio: um destino lento não atrasa mais as notificações de rotina e lembrete.
- A abertura do app faz menos consultas; a faxina das fotos usa o índice do histórico.

### Limpeza
- O tema claro tem um bloco só no `tokens.css` (eram duas cópias inteiras, e todo token novo ia nas duas); o `tema.js`
  marca sempre o tema que vale. Conferido no navegador: as 118 variáveis, em doze estados, iguais antes e depois.
- Código morto e duplicado: imports redundantes e dinâmicos do `app.js`, restos sem uso em `fotos.js`, `board.js` e no
  MCP, imports sem uso nos testes, e a regra da "hora do aparelho" numa função só (era uma no cronômetro e outra nas
  anotações).

### Documentação
- `docs/API.md`: `get_week` na lista de ferramentas da IA; a cota de fotos é a variável `PHOTO_QUOTA_MB` e o limite
  retroativo é fixo em 60 dias (o texto ainda falava nas opções do Admin).

## 2.0.4 — 2026-11-02
Android: o Enter do teclado no registro rápido do Hoje registra. Com o seletor de projeto no mesmo formulário, o
Chrome do Android trocava o Enter por "próximo" (pulava para o projeto); o seletor saiu do formulário do campo.

## 2.0.3 — 2026-11-02
Celular: o registro de uma linha do Hoje, o "+ Tarefa" dos projetos e o "Adicionar item" do checklist ganham o
botão de enviar (a seta) e passam a enviar pelo Enter do teclado em qualquer teclado (antes, alguns teclados mandavam
o Enter como tecla desconhecida e nada acontecia).

## 2.0.2 — 2026-11-02
Projeto aberto: "Todos os projetos" volta para cima do título, no cabeçalho da página (estava abaixo do título
e dos botões, fora de onde se procura a volta).

## 2.0.1 — 2026-11-02
Vencimentos no celular: o nome usa a largura toda, com o prazo e os botões embaixo (no Hoje, o nome
espremido ao lado dos botões quebrava no meio da palavra).

## 2.0.0 — 2026-11-02

Redesenho geral e quebras de contrato, resultado do "gauntlet geral" (rodadas de críticos, validação final
e lotes de correção).

### Quebras e mudanças de contrato
- **`POST /api/auth/link`** é a forma de abrir o link de convite ou de nova senha (o token vai no corpo,
  fora da URL e do log). `GET /api/auth/link` ainda responde, fora do log, mas é **obsoleto**: use POST.
- **`GET /api/assign/people`**: para quem não é admin, quem não pode receber tarefa vem só como
  `{accepts: false, everyone}`, sem id, e-mail nem bloqueio.
- **Pedido de convite agora é opt-in**: a tela de login só oferece "Solicitar convite" se o admin ligar em
  Admin > Para empresas (`invite_request_on`; a antiga `invite_request_off` saiu da API).
- **409** ao mudar o status de uma tarefa já concluída (antes aceitava); reabrir é a ação própria.
- **Aceite do visualizador**: contas novas começam sem permitir que quem tem o papel "Vê a equipe" veja o
  registro; a pessoa liga em Configurações > Conta (contas anteriores ficaram ligadas, sql/027).
- **Equipes** (sql/043): com pelo menos uma equipe cadastrada, "Vê a equipe" e "Manda tarefas" valem só entre
  quem compartilha uma equipe (app, API, MCP, CSV, PDF, painel e "Precisa de atenção"), e as opções de Para
  empresas só para quem está em alguma equipe (exceto pedido de convite e política de privacidade). Sem equipes,
  nada muda. `GET /api/me/visibility` passa a trazer só quem está no escopo, com `sees`/`assigns`.
- **Vencimentos compartilhados com uma equipe** (sql/044, `renewals.team_id`, opcional): todo membro vê, renova e
  vira tarefa na própria conta; só quem criou edita ou exclui; o aviso vai a cada membro uma vez; sem equipe nada
  muda. `GET /api/renewals` ganha `team_id`, `team_name`, `mine`, `owner_name`; novo `GET /api/renewals/teams`;
  `list_renewals` (MCP) inclui os da equipe, só leitura.
- **MCP**: as instruções que o servidor entrega ao conectar variam com o escopo da chave (só registrar
  × completa), trazem a versão do Nexus, e sessão antiga com ferramenta ou argumento velho recebe erro
  em português ("use /mcp, reconectar"); `listChanged` ligado em ferramentas e comandos.

### Simplificações
Menos opções e menos avisos; o que saiu continua aceito pela API até a 3.0 (marcado como obsoleto).
- **Sem sinal sem botão**: "Deixar pronto para sem sinal" deixou de ser botão (Hoje, Mais e Ajuda). O app guarda
  sozinho o detalhe das tarefas abertas ao abrir com rede e, no máximo, a cada 30 min (até 60, com a checagem de
  5 MB livres); a barra de sem conexão continua dizendo "N tarefas guardadas às HH:MM".
- **Configurações > Avisos**: sai o painel "Últimos envios"; fica uma linha de alerta só quando o último e-mail
  falhou (o detalhe segue em Saúde do Nexus; `GET /api/notifications` continua trazendo `recent`).
- **Configurações > IA e API**: "Receitas prontas" vira uma linha com o link para a página da API;
  "O que a IA pode fazer" encolhe para três linhas e o link da documentação.
- **Assistente**: sem a frase "resumo do dia" (só avisos acionáveis) e **sem aviso de tarefa parada**. Ao
  marcar **Aguardando**, o "Dia para cobrar" já vem sugerido para 5 dias úteis à frente (editável, pode limpar).
  Um só interruptor em Configurações; os demais valores são fixos.
- **Hoje**: sai o cartão "Esta semana" (a semana vive em Meu mês e na Revisão da semana); fica "Desde o último dia útil".
- **O que mudou para você**: os avisos únicos (visibilidade, receber tarefas, papéis, master, equipe) viram um
  só diálogo com um "Entendi" (`PUT /api/me/notices-seen`).
- **Avisos por canal**: e-mail liga/desliga (Seu dia, Antes de encerrar e Resumo da semana, em horários fixos) e
  notificações dos aparelhos liga/desliga (rotina e lembrete na hora seguem). Quem tinha algum tipo ligado
  fica com o canal ligado.
- **Fixos**: limite retroativo em 60 dias; cota de fotos pela variável `PHOTO_QUOTA_MB` (padrão 500); ambos
  saem de Admin > Geral.
- **Modelos de tarefa** saem da interface (Duplicar tarefa e os Pacotes de rotina cobrem o uso).
- **Pedido de convite**: além do campo-armadilha, tempo mínimo de preenchimento (3 s a 1 h, carimbo assinado
  pelo servidor; `GET /api/auth/invite-request/form`).
- Menos código: diálogos com largura por variável, avisos únicos num componente só, restos de Configurações removidos.

### Obsoleto: sai na 3.0
- Campos ignorados: `PUT /api/me/assistant` (`idle_*`, `reopen_*`, `summary_from`, `stale_days`);
  `PUT /api/notifications` (`morning`, `evening`, `weekly` e `*_hour`); `PUT /api/push/prefs` (`routine`,
  `follow_up`, `deadline`, `assigned`, `morning_hour`); `PUT /api/admin/settings` (`retro_days`, `photo_quota_mb`).
  As colunas ficam no banco (sem DROP), inclusive `app_settings.invite_request_off`, sem uso desde a sql/042.
- Rotas `/api/templates` e as ferramentas MCP `list_templates` e `create_from_template` (sem interface).
- `GET /api/auth/link` (use `POST`) será **removido** na 3.0.

### Navegação e telas
- **Equipe** absorve Atribuir (diálogo por cima da tela, "Tarefas que atribuí" logo abaixo) e vira um
  painel para coordenar, sem ranking nem comparação, só de quem aceitou ser visto.
- **Configurações** numa página só; **Meu mês** redesenhado (um seletor de mês, frase, painel, PDF como
  botão); tela **Aguardando**; **Duplicar tarefa**; tour de 4 paradas, obrigatório para conta nova.
- Tema híbrido (claro e escuro) e passe visual M3; listas grandes paginadas (sem rolagem infinita).
- Botões dos avisos de lembrete e rotina com 44 px no celular.

### Recursos
- **Para empresas** (Admin): visibilidade da equipe, receber tarefas atribuídas ("Todos recebem de quem
  atribui"), nome e e-mail definidos pela administração, endereço do sistema de chamados, política de
  privacidade (login, Conta e convite) e pedido de convite no login.
- **Equipes** (Admin > Equipes): várias por pessoa, membros em lote, arquivar; coluna e filtro em Contas;
  equipes no convite e em Contas > ⋮ > Equipes…; seletor de equipe na tela Equipe; Atribuir agrupado por equipe;
  a Conta mostra as equipes da pessoa e quem pode vê-la ou mandar tarefas agora.
- **Admin master** (o primeiro admin): com os próprios papéis ligados (um toque), vê e atribui para todos, com
  ou sem equipe; o que ele abre de outras pessoas vai ao log de admin; transferência só por ele, com senha e
  código de uso único mandado ao e-mail.
- Convite com **nome e papéis** já definidos, convite a partir de pedido, cancelar convite, último acesso e
  filtros na lista de contas, redefinir senha por link, **bloquear acesso**, transferir tarefas ao bloquear
  ou excluir, aviso de papel novo.
- **Devolver tarefa atribuída** (com motivo), reatribuir, encerrar; aviso do atribuidor no Hoje.
- **Revisão da semana** guiada, **Primeiro amanhã**, rotinas com **passos**, pausa até uma data, ordem
  própria, **pacotes por área** (Manutenção predial, Suporte de TI, Atendimento, Redes e campo, Segurança);
  lembrete com hora em tarefa; projetos com ícone e visão nova; objetivos.
- **Saúde do Nexus** com versão, último backup, e-mail, push, fotos e webhooks; "Copiar diagnóstico".
- API: `external_ref` em tudo, feed de mudanças, webhooks assinados com botão Testar, chaves "só registrar"
  com agenda, `get_period`, `create_recurring`, pacotes pelo MCP; contrato em `docs/openapi.json`.
- Limpeza de código morto (CSS, JS e Python) sem mudar comportamento; 544 testes.

### Banco
- Migrações `sql/027` a `sql/044`, todas aditivas e idempotentes (nada a fazer além do `./deploy.sh`).

## 1.12.1 — 2026-11-01
Relatórios: só um período marcado quando dois coincidem.

## 1.12.0 — 2026-10-31 ~
Subtítulo abaixo do título, barra do celular sempre com a marca, passo de tema no tour.

## 1.11.0 — 2026-10-31
Tema claro, pedido de convite, avatar padrão, áreas de toque de 44 px.

## 1.10.0 — 2026-10-31
App instalável: atalhos, compartilhar para o Nexus, Web Push, passkeys, fotos, funciona sem sinal, barra do
topo no celular.

## 1.9.1 — 2026-10-31
Endereços sem `.html` (app em `/`, login em `/login`); os antigos redirecionam (301) e o `#fragmento` é mantido.

## 1.9.0 — 2026-10-31
Hora e alarme nas rotinas, visão expandida da tarefa, menu compacto no hover.

## 1.8.0 — 2026-10-29
A IA cria projetos e objetivos pelo MCP (5 ferramentas novas).

## 1.7.0 — 2026-10-29
Projetos com objetivos em ordem de execução.

## 1.6.0 — 2026-10-29
Filtro no Hoje, tarefa em vários projetos, projeto padrão, tour, convite por link, recuperar senha, PDF
editorial, resumo semanal em PDF, retrospectiva por mês. `project_id` continua aceito.

## 1.5.0 — 2026-10-28
Material 3 (celular e computador); a tarefa abre em leitura e o lápis edita; movimento.

## 1.4.2 — 2026-10-28
Fluidez: telas instantâneas na volta, resumo bem mais leve, sem pulo de página.

## 1.4.1 — 2026-10-28
Tarefas e Atribuir não ficam mais presas em "Carregando…".

## 1.4.0 — 2026-10-25
Bloqueio com cobrança, passagem de turno, evidência nas rotinas, vencimentos, "como resolveu" e "já
resolvido antes", registro rápido com marcadores, CSVs de plantão e rotinas.

## 1.3.1 — 2026-10-25
Hotfix: cronômetro esquecido por dias não trava mais concluir, parar ou trocar de tarefa.

## 1.3.0 — 2026-10-25
Exclusão de conta (LGPD), saúde e vigia do servidor, links diretos, Ajuda, dependências atualizadas.

## 1.2.0 — 2026-10-24
Lançamento retroativo (app e IA), papéis acumuláveis, atribuição de tarefas, Equipe/visualizador, Admin em
abas. A migração dos papéis deu o papel visualizador aos admins existentes, sem perda.

## 1.1.0 — 2026-10-13
Assistente do dia, perfil e foto, cronômetro, número do chamado e plantão, modelos de tarefa, fechamento do
dia, atalhos de teclado. Inclui a correção do nginx em `/api/calendar`.

## 1.0.0 — 2026-10-12
Reconstrução e primeira versão que cumpre o mínimo para uso real por quem não é o autor: Hoje, projetos,
prioridade, checklist, tempo apontado, agendas flexíveis, passado das rotinas preservado, resumos, busca,
retrospectiva, ICS e e-mail, chaves de API e MCP, suíte de testes, três rodadas de revisão. Banco preservado.

## 0.4.0 — 2026-10-11
Cadastro público fechado; contas criadas pelo admin com senha temporária. IP real no limite de tentativas,
deploy com `pg_dump` verificado, dias úteis por usuário, marcação retroativa de rotina, túnel no host.

## 0.3.0 — 2026-07-14 ~
Painel analítico (KPIs, tendência, backlog), layout compacto, logo nova.

## 0.2.0 — 2026-07-10 ~
PWA instalável, Relatórios como tela de PDF, admin redefine senha, só tema escuro.

## 0.1.0 — 2026-07-01 ~
Primeira versão: tarefas, rotinas recorrentes, painel de pizzas, PDF, `deploy.sh`.
