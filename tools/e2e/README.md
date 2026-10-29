# Testes de ponta a ponta (homologação)

Rodam no navegador (Chromium headless, via CDP) contra a homologação. Complementam
a suíte do backend (`docker compose -f docker-compose.test.yml run --rm --build tests`):
aqui entram a tela, o fluxo de e-mail e o PDF de verdade.

Pré-requisitos (na máquina que roda o navegador):

- túnel para a homologação: `ssh -N -L 8090:127.0.0.1:8090 -L 8025:127.0.0.1:8025 giratina.shadow.tec.br`
  (8025 = Mailpit, a caixa de e-mail da homologação);
- `chromium` no PATH e `pip install websocket-client`;
- credenciais da homologação no ambiente (nunca no repositório):
  `NEXUS_E2E_USER=email:senha` (conta com dados de demonstração) e
  `NEXUS_E2E_ADMIN=email:senha` (admin; só para `e2e_convite.py`).

| Roteiro | O que confere |
|---|---|
| `e2e_tour.py SAIDA desktop\|mobile` | tour guiado (configuração + passeio), filtro do Hoje, vários projetos, projeto padrão |
| `tour_paradas.py desktop\|mobile` | o passeio mostra todas as paradas abrindo a Ajuda de outras telas |
| `e2e_convite.py SAIDA desktop\|mobile` | convite por link, esqueci a senha (Mailpit), confirmação de senha, semanas do resumo |
| `pdfs_exemplo.py SAIDA` | baixa o PDF da semana, do mês e de um projeto (ver com `pdftoppm -png`) |

`SAIDA` é a pasta das capturas. Cada roteiro imprime `OK`, `FALHAS` e os erros de
JavaScript da página. O limite de "esqueci a senha" (3 por hora por e-mail) fica
na memória do backend: entre execuções seguidas de `e2e_convite.py`, reinicie o
backend (`docker compose restart backend`).
