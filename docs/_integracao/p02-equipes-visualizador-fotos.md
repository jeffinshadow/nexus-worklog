# p02 — Equipes, visualizador, fotos e administração de contas

Branch `lab/p02-equipes-visualizador-fotos`. Sem migration (a 046 reservada não foi usada), sem dependência nova,
sem opção nova. Testes novos em `backend/tests/test_aud_p02.py` (13).

## Linhas para o CHANGELOG

### Segurança e privacidade
- **Arquivar a última equipe não abre mais o escopo.** A instância "usa equipes" enquanto houver alguma equipe
  cadastrada, ativa ou arquivada (`teams.ANY_SQL`). Com todas arquivadas, ninguém compartilha equipe: quem tem
  "Vê a equipe" ou "Manda tarefas" não alcança ninguém (só o admin master), e "Para empresas" não vale para ninguém.
  Só **excluir** a última equipe devolve o uso pessoal: `DELETE /api/admin/teams/{id}` responde `last: true` e a tela
  avisa antes (diálogo) e depois (aviso). Antes, arquivar a última fazia todo mundo alcançar todo mundo.
- `GET /api/export/fotos.zip` sai com `Cache-Control: no-store` e passa a incluir a **foto de perfil**
  (`perfil/foto-de-perfil.<ext>`); conta só com foto de perfil já baixa o zip (antes, 404).
- Fotos (`GET /api/photos/{id}`) e foto de perfil (`GET /api/me/avatar/{id}`) respondem com `Vary: Cookie`: depois
  de Sair, o navegador não reaproveita a cópia guardada.
- Foto de outra pessoa aberta pelo admin master entra no log de admin (`master.view`, `what: fotos`), uma linha por
  pessoa por dia. O "dia" do `master.view` passou a ser o do app (`APP_TZ`), não o do banco em UTC.
- Quadro de quem acompanha (`GET /api/viewer/users/{id}/board`): `timer` vem sempre `null` e as tarefas saem sem
  `remind_at`, `first_on` e `touched_at`. `GET /api/viewer/team`: `people[].last_activity` é só a data
  (`AAAA-MM-DD`, no fuso do app), sem hora.
- Redefinir senha com **senha temporária**: com e-mail configurado, a pessoa recebe um aviso de que quem administra
  redefiniu a senha (quem e quando), sem a senha. A resposta ganha `notified`.

### Corrigido
- **Excluir conta avisa dos vencimentos da equipe**: o diálogo mostra "N vencimentos compartilhados com a equipe X
  serão apagados" (`GET /api/admin/users` ganha `shared_renewals: [{team, count}]`), e a resposta de
  `POST /api/admin/users/{id}/delete` (e o log `user.delete`) conta `renewals` e `shared_renewals`.
- "Precisa de atenção" (Equipe): não lista mais as tarefas de quem está olhando e diz "e mais N itens" quando há
  mais do que os 6 mostrados (`attention_total` em `GET /api/viewer/team`).
- Transferir tarefas (bloquear/excluir conta) para quem as tinha atribuído zera `assigned_by`/`assigned_at`: elas
  viram tarefas da pessoa e saem de "Tarefas que atribuí".
- Admin › Contas no computador: duas linhas por conta (papéis e equipes juntos; "criada · último acesso" à direita).
  De ~93 px para ~57 px por conta. No celular, igual a antes.

## Mudanças de API (o integrador regera o `docs/openapi.json`)
Nenhuma rota nem parâmetro novo; só campos de resposta e descrições. O `test_openapi_em_dia` **falha** neste branch
(única falha da suíte: 604 passaram, 1 pulado) porque as descrições de `delete_team`, `list_users`, `delete_user` e
`export_zip` mudaram: basta rodar `tools/openapi.py`.
- **Removidos da resposta** de `GET /api/viewer/users/{id}/board`: `remind_at`, `first_on`, `touched_at` nas tarefas;
  `timer` sempre `null`. Usada só pela tela Equipe (`board.js` em modo leitura lida com a ausência: conferido).
- **Mudou de formato**: `people[].last_activity` em `GET /api/viewer/team` (era data e hora, agora só a data).
  `equipe.js` foi ajustado (e perdeu a dica com a hora exata).
- **Novos campos**: `last` (DELETE equipe), `attention_total` (painel), `shared_renewals` (lista de contas),
  `renewals`/`shared_renewals` (excluir conta), `notified` (reset com senha temporária).
- `docs/API.md` não foi tocado (não é do pacote): se ele descreve esses campos, precisa da mesma atualização.

## Fora da lista de arquivos (necessário)
- `backend/tests/test_equipes.py::test_instancia_sem_equipes_funciona_como_antes`: a última asserção afirmava o
  comportamento antigo ("equipe só arquivada não liga o escopo"), que é exatamente o achado. Troquei 1 asserção por
  3 (arquivada mantém o escopo; excluir a última devolve o uso pessoal).
- `web/static/css/app.css`: só o bloco no fim, entre `/* auditoria p02 */` e `/* fim auditoria p02 */`.

## Pendências e ressalvas
- `teams.any_active()` manteve o nome (é chamado em `org.py`, fora do pacote), mas agora significa "há equipe
  cadastrada". Renomear fica para quem integrar, se quiser.
- Efeito colateral aceito do item da última equipe: com todas as equipes arquivadas, `teams_on` segue `true` e
  quem via alguém só pela equipe deixa de ver até desarquivar ou excluir. `docs/ADMIN.md` (linhas 100-101) diz isso.
- Outros trechos de documentação que falam em "nenhuma equipe ativa" (resto do `docs/ADMIN.md`, do p06; `docs/API.md`)
  não foram revisados.
- O aviso de vencimentos no diálogo de excluir usa a lista de contas já carregada: se alguém compartilhar um
  vencimento depois de a tela abrir, o diálogo não mostra (a resposta e o log contam certo).
- Vencimentos compartilhados com equipe **arquivada** também entram na contagem (continuam ligados à equipe).
- O e-mail do reset com senha temporária vai em segundo plano (`_spawn`): `notified: true` quer dizer "e-mail
  configurado, envio disparado", não "entregue".
- `Vary: Cookie` só resolve o reaproveitamento pelo cache HTTP do navegador; a cópia do service worker (se houver)
  não foi verificada.
- Não implementado (fora do pacote, decisão do dono): transferência de vencimentos, `log_master_view` para todo
  admin, EXIF no servidor, e-mail de aviso do "Visível para quem gerencia", abrir a lista inteira de "Precisa de atenção".
