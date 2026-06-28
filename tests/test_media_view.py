from PySide6.QtGui import QColor, QPixmap

from mys_ui.widgets.media_view import MediaView


def test_image_ref_renders_pixmap(qtbot, tmp_path):
    p = tmp_path / "pic.png"
    pm = QPixmap(20, 20)
    pm.fill(QColor("red"))
    assert pm.save(str(p), "PNG")
    mv = MediaView(str(p))
    qtbot.addWidget(mv)
    assert mv.is_image is True
    assert not mv.image.pixmap().isNull()


def test_non_image_ref_renders_link(qtbot, tmp_path):
    mv = MediaView("doc_report.pdf")
    qtbot.addWidget(mv)
    assert mv.is_image is False
    assert "doc_report.pdf" in mv.link.text()
