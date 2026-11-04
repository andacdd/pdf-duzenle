# PDF Düzenle

- **Amaç:** PDF'teki yazıların fontunu, boyutunu, rengini, kalın/italik ayarını değiştirmek. Yazıyı yerinde düzenlemek, silmek ve yeni yazı eklemek. Arayüz Google Docs'a benzer şekilde çalışır.
- **Durum:** çalışıyor (v1.0)
- **Başlangıç:** 2026-11-04

## Nasıl açılır

| Bilgisayar | Ne yapılır |
| --- | --- |
| Mac | `PDF-Duzenle.command` dosyasına çift tıkla |
| Windows | `PDF-Duzenle-Windows.bat` dosyasına çift tıkla |

Uygulama tarayıcıda `http://localhost:8517` adresinde açılır. Açılan terminal penceresi açık kaldığı sürece çalışır.

İlk açılışta `uv` aracı yoksa kurmak isteyip istemediğini sorar. Kurulumu astral.sh'den indirir. Sonra gerekli Python paketlerini indirir; bu 1-2 dakika sürer. Sonraki açılışlar birkaç saniye.

Mac ilk seferde "geliştirici doğrulanamadı" uyarısı verebilir. O zaman dosyaya sağ tıkla → **Aç** → **Aç**.

## Kullanım

- **Seç:** yazıya tıkla. Çoklu seçim için Shift+tıkla ya da boş alandan sürükle. `⌘A` / `Ctrl+A` bütün belgeyi seçer.
- **Biçim:** seçince üstte çıkan çubuktan font, boyut, kalın, italik ve renk değiştir.
- **Düzenle:** yazıya çift tıkla (ya da seçip Enter'a bas), yaz, Enter'a bas. Vazgeçmek için Esc.
- **Taşı:** seçili yazıyı sürükle. İnce ayar için ok tuşları (1 pt), Shift+ok (10 pt).
- **Sil:** seç, Delete'e bas ya da çöp kutusuna tıkla.
- **Ekle:** sayfada boş bir yere çift tıkla, yaz, Enter'a bas. Son kullandığın font ve boyut kullanılır.
- **Geri al:** `⌘Z` / `Ctrl+Z` ya da Geri al butonu.
- **Kaydet:** İndir butonu `<ad>-duzenlendi.pdf` dosyasını indirir. Orijinal dosyaya dokunulmaz.

Font listesi bilgisayarda yüklü fontlardan gelir. Listede "Türkçe harf yok" yazan fontlarda ş, ğ, ı gibi harfler yoktur. Kendi fontunu kullanmak için `.ttf`/`.otf` dosyasını `fonts/` klasörüne koyup uygulamayı yeniden başlat.

## İş arkadaşıyla paylaşma

1. **Kendi bilgisayarında kullansın:** `dist/pdf-duzenle.zip` dosyasını gönder. Açıp yukarıdaki gibi çift tıklasın. Font listesi onun bilgisayarındaki fontlardan oluşur.
2. **Senin bilgisayarına bağlansın (aynı ağdaysanız):** `PDF-Duzenle-Agda-Paylas.command` dosyasını aç. Terminalde yazan `http://<ip>:8517` adresini iş arkadaşına gönder. Herkesin belgesi ayrı tutulur. Mac güvenlik duvarı izin isterse **İzin Ver** de.
   - Bu modda aynı ağdaki herkes adresi açabilir ve şifre yoktur. Hassas belgeler için kullanma, işin bitince pencereyi kapat.
   - PDF'ler sadece bellekte tutulur, diske yazılmaz. 6 saat kullanılmayan belge silinir.

## Sınırlar

- Yazı yeniden akmaz. Daha uzun bir metin ya da daha geniş bir font, satırın sonunda taşabilir. Satırı bölüp kısaltarak düzelt.
- Taranmış (resim) PDF'lerde seçilebilir yazı yoktur, önce OCR gerekir.
- Bazı PDF'lerde font Unicode eşlemesi taşımaz. Bu yazılar düzenlenemez, sadece silinebilir.
- Dönük (dikey/eğik) yazılar düzenlenemez.
- Yazının altındaki arka plan, görseller ve çizimler korunur.

## Dosyalar

- `server.py`: yerel web sunucusu (Flask)
- `static/index.html`: editör arayüzü
- `fontswap.py`: PDF motoru (PyMuPDF). Eski metni redaksiyonla siler ve aynı konuma yeni fontla yazar. Yeni font PDF'e alt küme olarak gömülür.
- `tests/`: motor testleri. Çalıştırmak için: `uv run pytest tests`
- `dist/pdf-duzenle.zip`: paylaşım paketi

## Lisans notu

PyMuPDF AGPL lisanslıdır. Uygulamayı şirket içinde kullanmak ve paylaşmak sorun değil. Ama ağ üzerinden dışarıya hizmet olarak sunulursa kaynak kodu da paylaşılmalıdır.
