# Testes de ponta a ponta (homologação)

Rodam no navegador (Chromium headless, via CDP) contra a homologação. Complementam
a suíte do backend (`docker compose -f docker-compose.test.yml run --rm --build tests`):
aqui entram a tela, o fluxo de e-mail e o PDF de verdade.

Pré-requisitos (na máquina que roda o navegador):

- túnel para a homologação: `ssh -N -L 8090:127.0.0.1:8090 -L 8025:127.0.0.1:8025 giratina.shadow.tec.br`
  (8025 = Mailpit, a caixa de e-mail da homologação);
- `chromium` no PATH e `pip install websocket-client`;
- para os roteiros que mexem nos containers da homologação: `NEXUS_E2E_SSH` (host SSH) e,
  se a pasta não for `/srv/docker/nexus-worklog`, `NEXUS_E2E_DIR`;
- credenciais da homologação no ambiente (nunca no repositório):
  `NEXUS_E2E_USER=email:senha` (conta com dados de demonstração) e
  `NEXUS_E2E_ADMIN=email:senha` (admin; só para `e2e_convite.py`).

| Roteiro | O que confere |
|---|---|
| `e2e_tour.py SAIDA desktop\|mobile` | tour guiado (configuração + passeio), filtro do Hoje, vários projetos, projeto padrão |
| `tour_paradas.py desktop\|mobile` | o passeio mostra todas as paradas abrindo a Ajuda de outras telas |
| `e2e_convite.py SAIDA desktop\|mobile` | convite por link, esqueci a senha (Mailpit), confirmação de senha, semanas do resumo |
| `e2e_objetivos.py SAIDA desktop\|mobile` | menu Projetos, objetivos em ordem, tarefas vinculadas, arrastar (computador) e ⋮ (celular), status e progresso |
| `e2e_instalar.py SAIDA` | convite para instalar (Chrome e iPhone), atalhos do ícone, compartilhar (com e sem sessão), número no ícone, manifest instalável |
| `e2e_notificacoes.py SAIDA` | painel de notificações, ligar o aparelho, convite depois de instalado, notificação entregue ao service worker e os botões Marcar feita / Adiar (precisa de `NEXUS_E2E_SSH`) |
| `e2e_passkey.py SAIDA` | passkey com o autenticador virtual do Chrome: cadastrar, entrar pelo botão e pela sugestão do campo, remover (a homologação precisa de `APP_URL=http://localhost:8090`) |
| `e2e_fotos.py SAIDA` | foto grande reduzida a 1600 px em WebP, print colado, visualizador, excluir e desfazer, evidência da rotina, compartilhar com foto. Em `SAIDA`: `foto-grande.jpg` e `print.png` (ex.: `magick -size 3000x2000 plasma:fractal foto-grande.jpg`) |
| `e2e_sem_sinal.py SAIDA` | desliga o nginx da homologação no meio (`NEXUS_E2E_SSH`), faz as seis ações sem servidor, religa e confere que tudo chegou, sem duplicar |
| `e2e_edicao.py SAIDA` | concluir espera o Pronto da edição (detalhe, cartão, menu; o status Concluída dentro da edição vale), testes de e-mail esperam salvar, evidência espera a foto |
| `e2e_tema_convite.py SAIDA` | pedido de convite na tela de login (e-mails pelo Mailpit), número no Admin e Convidar; tema da conta (claro, recarregar, automático); avatar padrão |
| `auditoria_toque.py` | celular (390 px): lista todo controle com área de toque menor que 44 px, em todas as telas, no detalhe da tarefa, na nova tarefa e nos menus ⋮ (conta a área estendida por `::after`) |
| `pdfs_exemplo.py SAIDA` | baixa o PDF da semana, do mês e de um projeto (ver com `pdftoppm -png`) |

`SAIDA` é a pasta das capturas. Cada roteiro imprime `OK`, `FALHAS` e os erros de
JavaScript da página. O limite de "esqueci a senha" (3 por hora por e-mail) fica
na memória do backend: entre execuções seguidas de `e2e_convite.py`, reinicie o
backend (`docker compose restart backend`).
