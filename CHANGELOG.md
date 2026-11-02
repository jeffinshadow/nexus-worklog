# Histórico de versões

Nexus Worklog segue [SemVer](https://semver.org/lang/pt-BR/): **MAJOR** = quebra de API/MCP ou
reforma profunda de como o app é usado; **MINOR** = recurso novo; **PATCH** = correção.
Quebras só em versão maior; rota ou campo antigo continua funcionando, marcado como obsoleto, até a
maior seguinte (política completa em [`docs/ADMIN.md`](docs/ADMIN.md#versionamento-e-compatibilidade) e
[`docs/API.md`](docs/API.md#versões-e-compatibilidade)). A versão atual fica em
`backend/app/version.py` (também no MCP e no `docs/openapi.json`). Datas marcadas com ~ são a do commit,
não a da hora do deploy. As versões 0.x e 1.x foram numeradas depois, sobre o histórico do git
(etiquetas `v0.1.0` … `v1.12.1`).

## 2.0.0 — a publicar

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
- **MCP**: as instruções que o servidor entrega ao conectar variam com o escopo da chave (só registrar
  × completa), trazem a versão do Nexus, e sessão antiga com ferramenta ou argumento velho recebe erro
  em português ("use /mcp, reconectar"); `listChanged` ligado em ferramentas e comandos.

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
- Limpeza de código morto (CSS, JS e Python) sem mudar comportamento; 526 testes.

### Banco
- Migrações `sql/027` a `sql/042`, todas aditivas e idempotentes (nada a fazer além do `./deploy.sh`).

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
