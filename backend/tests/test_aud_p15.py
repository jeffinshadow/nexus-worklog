"""Auditoria p15 (Hoje, avisos, lembretes, projeto, tour e vocabulário).

O pacote é de tela (JavaScript, conferido com Playwright no laboratório); do
backend só muda o rótulo do histórico, que passa a usar o mesmo verbo dos outros
("excluiu")."""
from app.routers.history import ACTION_LABELS


def test_rotulo_do_item_de_checklist_excluido():
    assert ACTION_LABELS["checklist.delete"] == "excluiu o item"
    # o vocabulário de apagar é um só no histórico
    assert not [k for k, v in ACTION_LABELS.items() if v.startswith("removeu o item")]
