"""Motor testleri: .venv/bin/python -m pytest tests  (proje kökünden)"""

import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fontswap as fs  # noqa: E402

ARIAL = "/System/Library/Fonts/Supplemental/Arial.ttf"
GEORGIA = "/System/Library/Fonts/Supplemental/Georgia.ttf"
TR = "Şirketimiz ığdır çğüöş İstanbul"


def _font(path):
    return fs.font_from_file(path)


def make_sample() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    # renkli arka plan kutusu ve bir çizgi (korunmalı)
    page.draw_rect(pymupdf.Rect(40, 40, 400, 140), color=None, fill=(1, 1, 0.6))
    page.draw_line((40, 150), (400, 150), color=(0, 0, 1), width=2)
    # sıkışık satırlar: Arial (değişecek)
    page.insert_font(fontname="A", fontbuffer=Path(ARIAL).read_bytes())
    page.insert_font(fontname="G", fontbuffer=Path(GEORGIA).read_bytes())
    page.insert_text((50, 70), TR, fontname="A", fontsize=12, color=(1, 0, 0))
    page.insert_text((50, 82), "İkinci satır sıkışık duruyor", fontname="A", fontsize=12)
    # aynı satırda iki farklı font: Arial + Georgia (Georgia kalmalı)
    page.insert_text((50, 110), "Arial burada", fontname="A", fontsize=12)
    page.insert_text((128, 110), "Georgia kalır", fontname="G", fontsize=12)
    # görsel (korunmalı)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), 0)
    pix.set_rect(pix.irect, (0, 128, 0))
    page.insert_image(pymupdf.Rect(300, 200, 340, 240), pixmap=pix)
    p2 = doc.new_page()
    p2.insert_font(fontname="A", fontbuffer=Path(ARIAL).read_bytes())
    p2.insert_text((50, 70), "İkinci sayfa", fontname="A", fontsize=12)
    return doc.tobytes()


@pytest.fixture(scope="module")
def sample_pdf() -> bytes:
    return make_sample()


def _texts(pdf: bytes, page_no=0) -> dict[str, list[str]]:
    """Font ailesi -> o fonttaki metinler (boşluklar normalize)."""
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    out: dict[str, list[str]] = {}
    for span, _ in fs._spans(doc[page_no]):
        fam = fs.clean_font_name(span["font"]).split()[0].split("-")[0]
        fam = fam.removesuffix("MT")
        out.setdefault(fam, []).append(span["text"].replace("\xa0", " ").strip())
    return out


def _all_text(pdf: bytes, page_no=0) -> str:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    return doc[page_no].get_text().replace("\xa0", " ")


def test_analyze_lists_fonts(sample_pdf):
    fonts = fs.analyze(pymupdf.open(stream=sample_pdf, filetype="pdf"))
    assert {"ArialMT", "Georgia"} <= set(fonts)


def test_swap_replaces_only_mapped_font(sample_pdf):
    out, rep = fs.swap_fonts(sample_pdf, {"ArialMT": _font(GEORGIA)}, pages=[1])
    by_font = _texts(out)
    assert set(by_font) == {"Georgia"}
    for t in (TR, "İkinci satır sıkışık duruyor", "Arial burada", "Georgia kalır"):
        assert t in by_font["Georgia"]
    assert rep.replaced == 3 and not rep.skipped_missing_glyphs


def test_keeps_color_position_graphics_images(sample_pdf):
    out, _ = fs.swap_fonts(sample_pdf, {"ArialMT": _font(GEORGIA)})
    page = pymupdf.open(stream=out, filetype="pdf")[0]
    span = next(s for s, _ in fs._spans(page) if s["text"].replace("\xa0", " ") == TR)
    assert span["color"] == 0xFF0000
    assert span["origin"] == pytest.approx((50, 70), abs=0.5)
    assert len(page.get_images()) == 1
    assert len(page.get_drawings()) >= 2


def test_page_filter(sample_pdf):
    out, rep = fs.swap_fonts(sample_pdf, {"ArialMT": _font(GEORGIA)}, pages=[2])
    assert rep.replaced == 1
    assert set(_texts(out, 1)) == {"Georgia"}
    assert "Arial" in _texts(out, 0)


def test_missing_glyphs_are_skipped(sample_pdf):
    symbol = next((f for f in fs.system_fonts() if f.label.startswith("Symbol")), None)
    if symbol is None:
        pytest.skip("Symbol fontu yok")
    out, rep = fs.swap_fonts(sample_pdf, {"ArialMT": symbol})
    assert rep.skipped_missing_glyphs and rep.replaced == 0
    assert TR in _texts(out)["Arial"]


def test_system_fonts_and_ttc():
    fonts = fs.system_fonts()
    assert len(fonts) > 20
    helv = next(f for f in fonts if f.label == "Helvetica — Regular")
    assert helv.path.endswith(".ttc")
    font = pymupdf.Font(fontbuffer=fs.font_buffer(helv.path, helv.index))
    assert font.has_glyph(ord("A"))


def test_guess_font():
    assert fs.guess_font("ArialMT").label == "Arial — Regular"
    assert fs.guess_font("ABCDEF+Arial-BoldMT").label == "Arial — Bold"
    assert fs.guess_font("Georgia-Italic").label == "Georgia — Italic"
    assert fs.guess_font("SomeUnknownFont") is None


def test_delete_text(sample_pdf):
    out, rep = fs.delete_text(sample_pdf, "ığdır")
    assert rep.count == 1
    text = _all_text(out)
    assert "ığdır" not in text
    assert "Şirketimiz" in text and "İstanbul" in text
    assert "İkinci satır sıkışık duruyor" in text  # alttaki sıkışık satır sağlam
    assert len(pymupdf.open(stream=out, filetype="pdf")[0].get_images()) == 1


def test_replace_text_keeps_style(sample_pdf):
    out, rep = fs.replace_text(sample_pdf, "Arial burada", "Yeni yazı")
    assert rep.count == 1
    page = pymupdf.open(stream=out, filetype="pdf")[0]
    span = next(s for s, _ in fs._spans(page) if "Yeni" in s["text"])
    assert span["size"] == pytest.approx(12, abs=0.1)
    assert span["origin"][1] == pytest.approx(110, abs=0.5)
    assert "Arial" in span["font"]
    assert "Arial burada" not in _all_text(out)
    assert "Georgia kalır" in _all_text(out)


def test_replace_on_page_only(sample_pdf):
    out, rep = fs.replace_text(sample_pdf, "İkinci", "Üçüncü", pages=[2])
    assert rep.pages == {2}
    assert "İkinci satır" in _all_text(out, 0)
    assert "Üçüncü sayfa" in _all_text(out, 1)


def test_add_text(sample_pdf):
    out = fs.add_text(sample_pdf, 2, 72, 300, "Merhaba\nikinci satır",
                      fs.default_font(), size=14, color=(0, 0, 1))
    text = _all_text(out, 1)
    assert "Merhaba" in text and "ikinci satır" in text
    span = next(s for s, _ in fs._spans(pymupdf.open(stream=out, filetype="pdf")[1])
                if "Merhaba" in s["text"])
    assert span["color"] == 0x0000FF and span["size"] == pytest.approx(14, abs=0.1)


def _ids(pdf, page_no, text):
    return [s["id"] for s in fs.span_infos(pdf, page_no) if s["text"].strip() == text]


def test_span_infos(sample_pdf):
    spans = fs.span_infos(sample_pdf, 1)
    s = next(s for s in spans if s["text"] == TR)
    assert s["family"] == "Arial" and not s["bold"] and s["color"] == "#ff0000"
    assert s["size"] == 12


def test_edit_span_style(sample_pdf):
    ids = _ids(sample_pdf, 1, "Arial burada")
    out = fs.edit_spans(sample_pdf, 1, ids, family="Georgia", bold=True, size=16,
                        color="#0000ff")
    s = next(s for s in fs.span_infos(out, 1) if s["text"] == "Arial burada")
    assert (s["family"], s["bold"], s["size"], s["color"]) == ("Georgia", True, 16, "#0000ff")
    assert "Georgia kalır" in _all_text(out)


def test_edit_span_text_keeps_style(sample_pdf):
    ids = _ids(sample_pdf, 1, TR)
    out = fs.edit_spans(sample_pdf, 1, ids, text="Yeni başlık")
    s = next(s for s in fs.span_infos(out, 1) if s["text"] == "Yeni başlık")
    assert (s["family"], s["size"], s["color"]) == ("Arial", 12, "#ff0000")
    assert TR not in _all_text(out)
    assert "İkinci satır sıkışık duruyor" in _all_text(out)


def test_edit_span_delete_multi(sample_pdf):
    ids = _ids(sample_pdf, 1, TR) + _ids(sample_pdf, 1, "Arial burada")
    out = fs.edit_spans(sample_pdf, 1, ids, delete=True)
    t = _all_text(out)
    assert TR not in t and "Arial burada" not in t and "Georgia kalır" in t


def test_edit_errors(sample_pdf):
    with pytest.raises(fs.EditError):
        fs.edit_spans(sample_pdf, 1, [0, 1], text="x")
    with pytest.raises(fs.EditError):
        fs.edit_spans(sample_pdf, 1, _ids(sample_pdf, 1, TR), family="Symbol")


def test_add_text_styled(sample_pdf):
    out = fs.add_text_styled(sample_pdf, 1, 60, 400, "Eklenen", "Georgia", italic=True,
                             size=20, color="#00aa00")
    s = next(s for s in fs.span_infos(out, 1) if s["text"] == "Eklenen")
    assert s["family"] == "Georgia" and s["italic"] and s["size"] == 20


def test_repeated_edits_same_page_keep_glyphs(sample_pdf):
    # ikinci işlem, ilkinin alt kümeye inmiş fontunu kullanmamalı (kutu karakter hatası)
    out = fs.edit_spans(sample_pdf, 1, _ids(sample_pdf, 1, "Arial burada"), family="Georgia")
    out = fs.edit_spans(out, 1, _ids(out, 1, TR), family="Georgia", text="Zxq Wvj ÇĞÜ")
    out = fs.add_text_styled(out, 1, 60, 400, "Bir", "Arial")
    out = fs.add_text_styled(out, 1, 60, 430, "Yepyeni kelimeler", "Arial")
    page = pymupdf.open(stream=out, filetype="pdf")[0]
    assert {"Zxq Wvj ÇĞÜ", "Yepyeni kelimeler"} <= {
        s["text"].replace("\xa0", " ") for s, _ in fs._spans(page)}
    # glif 0 = .notdef = ekranda kutu
    notdef = [chr(c[0]) for t in page.get_texttrace() for c in t["chars"]
              if c[1] == 0 and not chr(c[0]).isspace()]
    assert not notdef, notdef


def test_move_span_keeps_style_and_neighbors(sample_pdf):
    ids = _ids(sample_pdf, 1, TR)
    out = fs.edit_spans(sample_pdf, 1, ids, dx=30, dy=200)
    s = next(s for s in fs.span_infos(out, 1) if s["text"] == TR)
    before = next(s for s in fs.span_infos(sample_pdf, 1) if s["text"] == TR)
    assert s["bbox"][0] == pytest.approx(before["bbox"][0] + 30, abs=0.5)
    assert s["bbox"][3] == pytest.approx(before["bbox"][3] + 200, abs=0.5)
    assert (s["family"], s["size"], s["color"]) == ("Arial", 12, "#ff0000")
    assert "İkinci satır sıkışık duruyor" in _all_text(out)
    assert len(pymupdf.open(stream=out, filetype="pdf")[0].get_images()) == 1
