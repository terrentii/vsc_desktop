from mys_ui.dialogs.phrase import DEFAULT_RENDEZVOUS, PhraseDialog


def test_default_rendezvous_url(qtbot):
    d = PhraseDialog()
    qtbot.addWidget(d)
    assert d.rendezvous_url() == DEFAULT_RENDEZVOUS
    assert DEFAULT_RENDEZVOUS == "wss://soufos.ru/p2p"


def test_returns_phrase_and_rendezvous_stripped(qtbot):
    d = PhraseDialog()
    qtbot.addWidget(d)
    d.field.setText("  секрет  ")
    d.rendezvous.setText("  ws://10.0.0.5:8765/p2p  ")
    assert d.phrase() == "секрет"
    assert d.rendezvous_url() == "ws://10.0.0.5:8765/p2p"
