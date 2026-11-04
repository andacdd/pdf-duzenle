"""PDF içindeki metnin fontunu değiştiren motor.

Yöntem: her metin parçasının (span) konumu, boyutu ve rengi okunur; eski metin
redaksiyonla sayfadan silinir (görseller ve çizimler korunur); aynı metin aynı
taban çizgisine yeni fontla yeniden yazılır. Yeni font PDF'e alt küme olarak
gömülür.
"""

from __future__ import annotations

import io
import logging
import os
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pymupdf
from fontTools.ttLib import TTCollection, TTFont

FONT_DIRS = [
    # macOS
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
    # Windows
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
    Path(os.environ.get("LOCALAPPDATA", "~")) / "Microsoft/Windows/Fonts",
    # Linux
    Path("/usr/share/fonts"),
    Path.home() / ".local/share/fonts",
    # projeye eklenen fontlar
    Path(__file__).resolve().parent / "fonts",
]
TURKISH = "çğıöşüÇĞİÖŞÜ"


def _alias() -> str:
    """Her işlemde yeni bir font kaynak adı. Aynı adı tekrar kullanmak, sayfadaki
    önceki işlemin alt kümeye indirilmiş fontunu getirir ve yeni harfler kutu çıkar."""
    return "K" + secrets.token_hex(4)
logging.getLogger("fontTools").setLevel(logging.ERROR)
SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


# --------------------------------------------------------------------------
# Hedef fontlar
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class FontChoice:
    label: str          # "Arial — Bold"
    path: str           # dosya yolu
    index: int = 0      # .ttc koleksiyonundaki yüz numarası
    turkish: bool = True
    ps: str = ""        # PostScript adı (ör. "Arial-BoldMT")


def _name(tt: TTFont, name_id: int) -> str:
    rec = tt["name"].getDebugName(name_id)
    return rec or ""


def _face_info(tt: TTFont) -> tuple[str, bool, str] | None:
    if "name" not in tt or "cmap" not in tt:
        return None
    family = _name(tt, 16) or _name(tt, 1)
    style = _name(tt, 17) or _name(tt, 2) or "Regular"
    if not family or family.startswith("."):  # gizli sistem fontları
        return None
    cmap = tt.getBestCmap() or {}
    turkish = all(ord(c) in cmap for c in TURKISH)
    return f"{family} — {style}", turkish, _name(tt, 6)


@lru_cache(maxsize=1)
def system_fonts() -> tuple[FontChoice, ...]:
    """Mac'te yüklü .ttf/.otf/.ttc fontları (her yüz ayrı seçenek)."""
    found: dict[str, FontChoice] = {}
    for d in FONT_DIRS:
        if not d.is_dir():
            continue
        files = d.iterdir() if d.parts[:3] == ("/", "System", "Library") else d.rglob("*")
        for p in sorted(files):
            ext = p.suffix.lower()
            try:
                if ext in (".ttf", ".otf"):
                    faces = [(0, TTFont(p, lazy=True, fontNumber=0))]
                elif ext == ".ttc":
                    faces = list(enumerate(TTCollection(p, lazy=True).fonts))
                else:
                    continue
                for i, tt in faces:
                    info = _face_info(tt)
                    if info and info[0] not in found:
                        found[info[0]] = FontChoice(info[0], str(p), i, info[1], info[2])
            except Exception:
                continue  # bozuk ya da desteklenmeyen dosya
    return tuple(sorted(found.values(), key=lambda f: f.label.lower()))


def font_from_file(path: str, index: int = 0) -> FontChoice:
    """Kullanıcının yüklediği font dosyasından seçenek üretir."""
    if path.lower().endswith(".ttc"):
        tt = TTCollection(path, lazy=True).fonts[index]
    else:
        tt = TTFont(path, lazy=True)
    info = _face_info(tt) or (Path(path).stem, False, "")
    return FontChoice(info[0], path, index, info[1], info[2])


@lru_cache(maxsize=64)
def font_buffer(path: str, index: int = 0) -> bytes:
    """Fontu PyMuPDF'in okuyabileceği tek yüzlü bayt dizisine çevirir."""
    if path.lower().endswith(".ttc"):
        tt = TTCollection(path).fonts[index]
        buf = io.BytesIO()
        tt.save(buf)
        return buf.getvalue()
    return Path(path).read_bytes()


# --------------------------------------------------------------------------
# PDF analizi
# --------------------------------------------------------------------------

def clean_font_name(name: str) -> str:
    return SUBSET_PREFIX.sub("", name or "")


@dataclass
class SourceFont:
    name: str
    spans: int = 0
    chars: int = 0
    pages: set[int] = field(default_factory=set)
    sizes: set[float] = field(default_factory=set)
    sample: str = ""


def _spans(page: pymupdf.Page):
    """Sayfadaki yatay ve dikey tüm metin parçaları: (span, line)."""
    data = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
    for block in data["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if span["text"].strip():
                    yield span, line


def analyze(doc: pymupdf.Document) -> dict[str, SourceFont]:
    fonts: dict[str, SourceFont] = {}
    for page in doc:
        for span, _ in _spans(page):
            name = clean_font_name(span["font"])
            sf = fonts.setdefault(name, SourceFont(name))
            sf.spans += 1
            sf.chars += len(span["text"])
            sf.pages.add(page.number + 1)
            sf.sizes.add(round(span["size"], 1))
            if len(sf.sample) < 60:
                sf.sample = (sf.sample + " " + span["text"].strip()).strip()[:60]
    return dict(sorted(fonts.items(), key=lambda kv: -kv[1].chars))


# --------------------------------------------------------------------------
# Font değiştirme
# --------------------------------------------------------------------------

@dataclass
class SwapReport:
    replaced: int = 0
    skipped_missing_glyphs: list[str] = field(default_factory=list)
    skipped_unreadable: int = 0
    skipped_rotated: int = 0
    pages_changed: set[int] = field(default_factory=set)

    def summary(self) -> str:
        parts = [f"{self.replaced} metin parçası değişti "
                 f"({len(self.pages_changed)} sayfada)."]
        if self.skipped_missing_glyphs:
            chars = "".join(sorted(set("".join(self.skipped_missing_glyphs))))
            if len(chars) > 20:
                chars = chars[:20] + "…"
            parts.append(f"{len(self.skipped_missing_glyphs)} parça atlandı: "
                         f"yeni fontta şu karakterler yok: {chars}")
        if self.skipped_unreadable:
            parts.append(f"{self.skipped_unreadable} parça atlandı: metni "
                         "okunamıyor (fontun Unicode eşlemesi yok).")
        if self.skipped_rotated:
            parts.append(f"{self.skipped_rotated} parça atlandı: dönük metin.")
        return " ".join(parts)


def _rgb(color: int) -> tuple[float, float, float]:
    return ((color >> 16) & 255) / 255, ((color >> 8) & 255) / 255, (color & 255) / 255


def _missing(font: pymupdf.Font, text: str) -> str:
    return "".join(c for c in set(text)
                   if not c.isspace() and not font.has_glyph(ord(c)))


def _band(x0: float, x1: float, baseline: float, size: float) -> pymupdf.Rect:
    """Sadece bu satırın glifleriyle kesişen ince bir şerit.

    Komşu satırlara ve aynı satırdaki komşu parçalara dokunmamak için
    taban çizgisinin hemen üstünde, kenarlardan içeri çekilmiş bir bant.
    """
    inset = min(size * 0.15, (x1 - x0) * 0.25)
    return pymupdf.Rect(x0 + inset, baseline - size * 0.45,
                        x1 - inset, baseline - size * 0.15)


def _redact_rect(span: dict) -> pymupdf.Rect:
    x0, _, x1, _ = span["bbox"]
    return _band(x0, x1, span["origin"][1], span["size"])


def _apply_text_redactions(page: pymupdf.Page) -> None:
    page.apply_redactions(
        images=pymupdf.PDF_REDACT_IMAGE_NONE,
        graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        text=pymupdf.PDF_REDACT_TEXT_REMOVE,
    )


def swap_fonts(
    pdf_bytes: bytes,
    mapping: dict[str, FontChoice],
    pages: list[int] | None = None,
    keep_width: bool = True,
    size_scale: float = 1.0,
) -> tuple[bytes, SwapReport]:
    """mapping: kaynak font adı -> hedef font. pages: 1 tabanlı sayfa listesi."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    report = SwapReport()
    fonts = {src: pymupdf.Font(fontbuffer=font_buffer(fc.path, fc.index))
             for src, fc in mapping.items()}
    aliases = {src: _alias() for src in mapping}

    for page in doc:
        if pages and page.number + 1 not in pages:
            continue
        todo = []
        for span, line in _spans(page):
            src = clean_font_name(span["font"])
            if src not in mapping:
                continue
            text = span["text"]
            if "�" in text:
                report.skipped_unreadable += 1
                continue
            if tuple(round(v, 3) for v in line["dir"]) != (1.0, 0.0):
                report.skipped_rotated += 1
                continue
            miss = _missing(fonts[src], text)
            if miss:
                report.skipped_missing_glyphs.append(miss)
                continue
            todo.append((src, span))
        if not todo:
            continue

        for _, span in todo:
            page.add_redact_annot(_redact_rect(span), fill=False)
        _apply_text_redactions(page)

        inserted: set[str] = set()
        for src, span in todo:
            alias = aliases[src]
            fc = mapping[src]
            if alias not in inserted:
                page.insert_font(fontname=alias,
                                 fontbuffer=font_buffer(fc.path, fc.index))
                inserted.add(alias)
            size = span["size"] * size_scale
            text = span["text"]
            origin = pymupdf.Point(span["origin"])
            morph = None
            if keep_width:
                orig_w = span["bbox"][2] - span["bbox"][0]
                new_w = fonts[src].text_length(text, fontsize=size)
                if new_w > 0 and orig_w > 0:
                    sx = max(0.6, min(1.6, orig_w / new_w))
                    if abs(sx - 1) > 0.01:
                        morph = (origin, pymupdf.Matrix(sx, 1))
            page.insert_text(origin, text, fontsize=size, fontname=alias,
                             color=_rgb(span["color"]), morph=morph)
            report.replaced += 1
        report.pages_changed.add(page.number + 1)

    if report.replaced:
        try:
            doc.subset_fonts()
        except Exception:
            pass  # alt küme alınamazsa font tam gömülür
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out, report


# --------------------------------------------------------------------------
# Metin ekleme / silme / değiştirme
# --------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s).lower())


@lru_cache(maxsize=1)
def _exact_index() -> dict[str, FontChoice]:
    idx: dict[str, FontChoice] = {}
    for fc in system_fonts():
        fam, style = split_label(fc.label)
        for key in (fc.ps, fam + style, fam if style.lower() == "regular" else ""):
            if key:
                idx.setdefault(_norm(key), fc)
    return idx


def guess_font(pdf_font_name: str) -> FontChoice | None:
    """PDF'teki font adına (ör. 'Arial-BoldMT', 'Georgia Bold') en yakın yüklü font."""
    name = clean_font_name(pdf_font_name)
    exact = _exact_index().get(_norm(name))
    if exact:
        return exact
    family, _, style = name.partition("-")
    fam = _norm(re.sub(r"(PSMT|MT|PS)$", "", family))
    low = name.lower()
    want_bold = "bold" in low or "black" in low or "heavy" in low
    want_italic = "italic" in low or "oblique" in low
    best, best_score = None, -1
    for fc in system_fonts():
        f_family, _, f_style = fc.label.partition(" — ")
        if _norm(f_family) != fam:
            continue
        s = f_style.lower()
        score = (("bold" in s) == want_bold) * 2 + (("italic" in s or "oblique" in s) == want_italic) * 2
        score += s in ("regular", "roman", "book") and not (want_bold or want_italic)
        if score > best_score:
            best, best_score = fc, score
    return best


def default_font() -> FontChoice:
    for label in ("Arial — Regular", "Helvetica — Regular"):
        for fc in system_fonts():
            if fc.label == label:
                return fc
    return system_fonts()[0]


def _span_at(page: pymupdf.Page, rect: pymupdf.Rect) -> dict | None:
    """Arama sonucunun düştüğü metin parçası (font, boyut, renk, taban çizgisi)."""
    c = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    best = None
    for span, line in _spans(page):
        if tuple(round(v, 3) for v in line["dir"]) != (1.0, 0.0):
            continue
        b = pymupdf.Rect(span["bbox"])
        if b.contains(c):
            return span
        if best is None and b.intersects(rect):
            best = span
    return best


@dataclass
class EditReport:
    count: int = 0
    pages: set[int] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    def summary(self, verb: str) -> str:
        if not self.count:
            return "Eşleşme bulunamadı."
        pages = ", ".join(map(str, sorted(self.pages)))
        return " ".join([f"{self.count} yerde {verb} (sayfa: {pages})."] + self.notes)


def _target_pages(doc: pymupdf.Document, pages: list[int] | None):
    for page in doc:
        if not pages or page.number + 1 in pages:
            yield page


def _save(doc: pymupdf.Document) -> bytes:
    try:
        doc.subset_fonts()
    except Exception:
        pass
    out = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return out


def delete_text(pdf_bytes: bytes, needle: str,
                pages: list[int] | None = None) -> tuple[bytes, EditReport]:
    """Aranan metnin her geçtiği yeri siler. Arka plan, görsel ve çizimler kalır."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    rep = EditReport()
    for page in _target_pages(doc, pages):
        hits = page.search_for(needle)
        for r in hits:
            span = _span_at(page, r)
            band = _band(r.x0, r.x1, span["origin"][1], span["size"]) if span else r
            page.add_redact_annot(band, fill=False)
        if hits:
            _apply_text_redactions(page)
            rep.count += len(hits)
            rep.pages.add(page.number + 1)
    return _save(doc), rep


def replace_text(pdf_bytes: bytes, needle: str, replacement: str,
                 font: FontChoice | None = None,
                 pages: list[int] | None = None) -> tuple[bytes, EditReport]:
    """Aranan metni yenisiyle değiştirir; boyut, renk ve taban çizgisi korunur.

    font verilmezse orijinal fonta en yakın yüklü font seçilir.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    rep = EditReport()
    fallback_used: set[str] = set()

    def pick(span: dict) -> FontChoice:
        fc = font or guess_font(span["font"])
        if fc is None:
            fallback_used.add(clean_font_name(span["font"]))
            fc = default_font()
        return fc

    for page in _target_pages(doc, pages):
        # (silinecek bant, yazılacak metin, başlangıç x, span, font, eşleşme sayısı)
        jobs = []
        whole: list[pymupdf.Rect] = []
        # 1) Aranan metin tek bir parçanın içindeyse parçanın tamamı yeniden
        #    yazılır; böylece uzunluk değişse de satırın geri kalanı kayar.
        for span, line in _spans(page):
            text = span["text"].replace("\xa0", " ")
            n = text.count(needle)
            if not n or tuple(round(v, 3) for v in line["dir"]) != (1.0, 0.0):
                continue
            new = text.replace(needle, replacement)
            x0, _, x1, _ = span["bbox"]
            jobs.append((_redact_rect(span), new, x0, span, pick(span), n))
            whole.append(pymupdf.Rect(span["bbox"]))
        # 2) Parçalar arasına bölünmüş eşleşmeler: sadece eşleşen alan değişir.
        for r in page.search_for(needle):
            if any(w.contains(r.tl + (1, 1)) and w.contains(r.br - (1, 1)) for w in whole):
                continue
            span = _span_at(page, r)
            if span is None:
                continue
            band = _band(r.x0, r.x1, span["origin"][1], span["size"])
            jobs.append((band, replacement, r.x0, span, pick(span), 1))
        if not jobs:
            continue
        for band, *_ in jobs:
            page.add_redact_annot(band, fill=False)
        _apply_text_redactions(page)
        aliases: dict[tuple[str, int], str] = {}
        for _, new, x0, span, fc, n in jobs:
            key = (fc.path, fc.index)
            if key not in aliases:
                aliases[key] = _alias()
                page.insert_font(fontname=aliases[key],
                                 fontbuffer=font_buffer(fc.path, fc.index))
            if new.strip():
                page.insert_text((x0, span["origin"][1]), new,
                                 fontsize=span["size"], fontname=aliases[key],
                                 color=_rgb(span["color"]))
            rep.count += n
        rep.pages.add(page.number + 1)
    if fallback_used:
        rep.notes.append("Benzer font bulunamadı, Arial kullanıldı: "
                         + ", ".join(sorted(fallback_used)) + ".")
    return _save(doc), rep


def add_text(pdf_bytes: bytes, page_no: int, x: float, y: float, text: str,
             font: FontChoice, size: float = 12,
             color: tuple[float, float, float] = (0, 0, 0)) -> bytes:
    """Sayfaya yeni metin ekler. x, y: sol üstten pt cinsinden ilk satırın taban çizgisi.
    Birden çok satır için metinde satır sonu kullan."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_no - 1]
    alias = _alias()
    page.insert_font(fontname=alias, fontbuffer=font_buffer(font.path, font.index))
    page.insert_text((x, y), text, fontsize=size, fontname=alias, color=color)
    return _save(doc)


# --------------------------------------------------------------------------
# Editör: sayfadaki tek tek parçalar üzerinde işlem
# --------------------------------------------------------------------------

def split_label(label: str) -> tuple[str, str]:
    family, _, style = label.partition(" — ")
    return family, style or "Regular"


def is_bold(style: str) -> bool:
    s = style.lower()
    return any(w in s for w in ("bold", "black", "heavy", "semibold"))


def is_italic(style: str) -> bool:
    s = style.lower()
    return "italic" in s or "oblique" in s


def families() -> dict[str, list[FontChoice]]:
    """Aile adı -> o ailenin yüzleri."""
    out: dict[str, list[FontChoice]] = {}
    for fc in system_fonts():
        out.setdefault(split_label(fc.label)[0], []).append(fc)
    return out


def pick_face(family: str, bold: bool, italic: bool) -> FontChoice | None:
    """Ailede istenen kalın/italik yüzü seçer; yoksa en yakınını."""
    faces = families().get(family)
    if not faces:
        return None

    def score(fc: FontChoice) -> tuple:
        st = split_label(fc.label)[1]
        plain = st.lower() in ("regular", "roman", "book", "normal", "medium")
        return ((is_bold(st) == bold) * 2 + (is_italic(st) == italic) * 2,
                plain, -len(st))
    return max(faces, key=score)


def span_infos(pdf_bytes: bytes, page_no: int) -> list[dict]:
    """Editörün gösterdiği seçilebilir parçalar (id = sayfadaki sıra)."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_no - 1]
        out = []
        for i, (span, line) in enumerate(_spans(page)):
            fc = guess_font(span["font"])
            family, style = split_label(fc.label) if fc else (clean_font_name(span["font"]), "")
            out.append({
                "id": i,
                "bbox": [round(v, 2) for v in span["bbox"]],
                "text": span["text"].replace("\xa0", " "),
                "pdfFont": clean_font_name(span["font"]),
                "family": family,
                "bold": is_bold(style) if fc else bool(span["flags"] & 16),
                "italic": is_italic(style) if fc else bool(span["flags"] & 2),
                "known": fc is not None,
                "size": round(span["size"], 1),
                "color": "#%06x" % span["color"],
                "rotated": tuple(round(v, 3) for v in line["dir"]) != (1.0, 0.0),
            })
        return out


class EditError(ValueError):
    pass


def edit_spans(pdf_bytes: bytes, page_no: int, ids: list[int], *,
               text: str | None = None, family: str | None = None,
               bold: bool | None = None, italic: bool | None = None,
               size: float | None = None, color: str | None = None,
               delete: bool = False, dx: float = 0, dy: float = 0) -> bytes:
    """Seçili parçaları siler ya da yeni metin/stille yeniden yazar.

    None olan özellik parçanın kendi değerini korur. text yalnızca tek
    parça seçiliyken kullanılır. dx, dy: parçaları pt cinsinden taşır.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_no - 1]
    all_spans = list(_spans(page))
    try:
        chosen = [all_spans[i] for i in ids]
    except IndexError:
        raise EditError("Seçim güncel değil; sayfayı yenile.")
    if not chosen:
        raise EditError("Hiçbir şey seçilmedi.")
    if any(tuple(round(v, 3) for v in ln["dir"]) != (1.0, 0.0) for _, ln in chosen):
        raise EditError("Dönük metin düzenlenemiyor.")
    if text is not None and len(chosen) > 1:
        raise EditError("Metni değiştirmek için tek parça seç.")

    jobs = []
    if not delete:
        for span, _ in chosen:
            new_text = (text if text is not None else span["text"]).replace("\xa0", " ")
            if "�" in new_text:
                raise EditError("Bu metnin karakterleri okunamıyor (fontun Unicode "
                                "eşlemesi yok); sadece silinebilir.")
            orig = guess_font(span["font"])
            o_fam, o_style = split_label(orig.label) if orig else (None, "")
            fam = family or o_fam
            b = bold if bold is not None else (is_bold(o_style) if orig else bool(span["flags"] & 16))
            it = italic if italic is not None else (is_italic(o_style) if orig else bool(span["flags"] & 2))
            fc = (pick_face(fam, b, it) if fam else None) or default_font()
            font = pymupdf.Font(fontbuffer=font_buffer(fc.path, fc.index))
            miss = _missing(font, new_text)
            if miss:
                raise EditError(f"“{split_label(fc.label)[0]}” fontunda şu karakterler "
                                f"yok: {miss}. Başka font seç.")
            col = hex_to_rgb(color) if color else _rgb(span["color"])
            jobs.append((span, new_text, fc, size or span["size"], col))

    for span, _ in chosen:
        page.add_redact_annot(_redact_rect(span), fill=False)
    _apply_text_redactions(page)

    aliases: dict[tuple[str, int], str] = {}
    for span, new_text, fc, sz, col in jobs:
        if not new_text.strip():
            continue
        key = (fc.path, fc.index)
        if key not in aliases:
            aliases[key] = _alias()
            page.insert_font(fontname=aliases[key], fontbuffer=font_buffer(*key))
        ox, oy = span["origin"]
        page.insert_text((ox + dx, oy + dy), new_text, fontsize=sz,
                         fontname=aliases[key], color=col)
    return _save(doc)


def add_text_styled(pdf_bytes: bytes, page_no: int, x: float, y: float, text: str,
                    family: str, bold: bool = False, italic: bool = False,
                    size: float = 12, color: str = "#000000") -> bytes:
    fc = pick_face(family, bold, italic) or default_font()
    miss = _missing(pymupdf.Font(fontbuffer=font_buffer(fc.path, fc.index)), text)
    if miss:
        raise EditError(f"“{family}” fontunda şu karakterler yok: {miss}. Başka font seç.")
    return add_text(pdf_bytes, page_no, x, y, text, fc, size, hex_to_rgb(color))


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def page_sizes(pdf_bytes: bytes) -> list[tuple[float, float]]:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return [(p.rect.width, p.rect.height) for p in doc]


def render_page(pdf_bytes: bytes, page_no: int, zoom: float = 1.5) -> bytes:
    """Önizleme için sayfayı PNG olarak döndürür (1 tabanlı)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        pix = doc[page_no - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        return pix.tobytes("png")
    finally:
        doc.close()


def page_count(pdf_bytes: bytes) -> int:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc.page_count


if __name__ == "__main__":  # hızlı CLI: python fontswap.py in.pdf
    import sys
    with open(sys.argv[1], "rb") as f:
        d = pymupdf.open(stream=f.read(), filetype="pdf")
    for name, sf in analyze(d).items():
        print(f"{name:40} {sf.chars:6} kar.  sayfa {min(sf.pages)}-{max(sf.pages)}  {sf.sample!r}")
    print(len(system_fonts()), "sistem fontu,", os.cpu_count(), "çekirdek")
