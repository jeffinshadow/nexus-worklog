# r2-08-backend-ordenacao-rotinas

Ordem com acentos no visualizador e nas equipes; rotinas: trava no pausar e frases do desfazer.
Branch `lab/r2-08-backend-ordenacao-rotinas`, sobre `lab/integracao` (3694956). Só backend; nenhum JS, HTML, migration ou dependência.

## Linhas para o CHANGELOG

- **Equipe e Admin › Equipes**: nomes com acento ou em minúsculas entram no lugar certo da ordem alfabética ("Água", "almoxarifado", "Zeladoria"), no seletor de pessoas, nos cartões do painel da Equipe, nos projetos de uma pessoa (relatório por projeto) e nos membros de cada equipe. Antes, "Água" ia para o fim.
- **Rotinas › Pausar**: pausar a mesma rotina duas vezes ao mesmo tempo (duas abas, a IA que repete o pedido) não cria mais dois períodos de pausa sobrepostos; a segunda só muda o fim da primeira.
- **Histórico › Desfazer**: desfazer um "Retomar" de uma rotina que tinha duas pausas valendo reabre as duas, e não só a mais recente (vale para os "Retomar" feitos a partir desta versão).
- **Histórico › Desfazer**: ao tentar desfazer a edição de uma rotina cuja agenda foi trocada há mais de 7 dias, o aviso passou a dizer que a alteração não pode mais ser desfeita, em vez de mandar desfazer uma troca que já não tem desfazer.

## Mudanças de resposta de API (docs/API.md / openapi)

Nenhuma rota, parâmetro, campo ou status novo; o openapi não muda (test_openapi_em_dia passou).

- `GET /api/viewer/users`, `GET /api/viewer/team` (`people`), `GET /api/viewer/users/{id}/projects`, `GET/POST/PATCH /api/admin/teams` (`members`): só a ORDEM dos itens (sem acento e sem diferença de maiúsculas; projetos com desempate por id).
- `POST /api/history/{id}/undo`, 409 de `recurring.update`/`recurring.toggle` em rotina trocada: o `detail` passa a ser "a agenda desta rotina foi trocada há mais de 7 dias; esta alteração não pode mais ser desfeita" quando a troca (`recurring.replace`) tem mais de 7 dias; dentro da janela segue "a agenda desta rotina foi trocada depois; desfaça a troca primeiro". Se o API.md cita a frase, vale acrescentar a segunda.
- Interno (não sai em `GET /api/history`): o `before` da linha `recurring.resume` no audit_log ganha `pauses` (lista `{id, start_d, end_d}` de todas as pausas fechadas); `pause` continua sendo a mais recente. Linhas antigas, sem `pauses`, desfazem como antes (só a mais recente).

## O que mudou no código

- `viewer.py`: `labels.fold` nos dois sorts de pessoas; `ORDER BY archived, nx_fold(name), id` nos projetos da pessoa. `equipes.py`: `fold` em `_members`.
- `recurring.py`: `_active_routine` faz `SELECT ... FOR UPDATE` e `pause`/`resume` rodam em `db.transaction()` (a linha do histórico entra na mesma transação). O `resume` também ganhou a trava (não tinha): é o que garante que a lista `pauses` gravada é a que ele fechou.
- `history.py`: `_frase_trocada` escolhe a frase do 409; o desfazer de pausa/retomar percorre `before.pauses` quando existe.

## O que NÃO foi feito

- Nada pendente dos itens do pacote.
- Outros `lower(name)`/`.lower()` de ordenação fora dos arquivos do pacote não foram procurados nem tocados.
- O desfazer de um "Retomar" depois de uma troca de agenda (`_set_pause_today` na rotina nova) continua recriando UMA pausa na rotina atual, como antes: a rotina nova só nasce com uma.

## O que não foi verificado

- `test_desfazer_retomar_de_linha_antiga_reabre_a_mais_recente` passa também sem a correção: é guarda do comportamento antigo, não prova de defeito. Os outros cinco testes falham sem a correção (conferido com `git stash` do app).
- A corrida do pausar foi provada com a janela alargada por um `sleep` em `current_pause` (duas threads, duas sessões); não houve teste de carga real.
- A frase nova no caso `recurring.toggle` não tem teste: a marcação do dia da troca sai da janela de 7 dias antes (409 "já saiu da janela de edição"), então na prática a frase nova só aparece na edição (`recurring.update`).
- Tela: só a Equipe (`/#equipe`) foi aberta no a08 com Playwright, em 1440 e 390 px, sem erro de console, com dois nomes acentuados postos direto no banco; a ordem foi conferida pelas respostas da API no app de pé (viewer/users, viewer/team, admin/teams), não cartão a cartão na tela. Admin › Equipes e o seletor de projetos do relatório não foram abertos no navegador.
- Suíte inteira: 812 passaram (`lab.sh test 08`).
