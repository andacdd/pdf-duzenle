# Notlar

## Kararlar
- 2026-11-04: KillerPDF Windows-only, PdfCraft'ta font değişimi yok → kendi aracımız.
- Motor: PyMuPDF. Yöntem: span'i ince bir bantla redakte et (komşu satırlar ve görseller kalsın), aynı taban çizgisine yeni fontla yaz.
- Her işlemde yeni font kaynak adı (`_alias()`): aynı ad, önceki işlemin alt kümelenmiş fontunu getiriyordu → harfler kutu çıkıyordu (test: test_repeated_edits_same_page_keep_glyphs).
- Arayüz: Streamlit denendi, karmaşık bulundu → Flask + tek sayfa, Docs benzeri seç-düzenle.
- Paylaşım: uv ile çift tık başlatıcı (Mac/Windows) + `--paylas` LAN modu, oturum başına ayrı belge.

## Açık işler
- Yazı akışı yok: uzun metin satırdan taşar.
- Çok satırlı paragraf düzenleme yok (her satır ayrı parça).
