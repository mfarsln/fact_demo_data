# FACT Demo — Günlük "Canlı" Dummy Veri

Statik FACT verisini her gün otomatik büyüyen, gerçek akan veri gibi görünen bir kaynağa çevirir.

## Nasıl çalışır?

- `data/fact.csv` — tüm geçmiş (orijinal QVD verisi, tarihler bugüne kaydırılmış: 2023-10-04 → bugün).
- `generate_daily.py` — eksik her gün için geçmişten bootstrap örnekleme ile yeni satırlar üretir.
  Bölge→Şehir→İlçe→Mağaza ve Ürün hiyerarşileri her zaman tutarlıdır; ciro/kâr bazen artar bazen düşer,
  Kasım-Aralık'ta hafif mevsimsel yükseliş vardır. Script idempotent: aynı gün iki kez çalışsa veri şişmez.
  Cron kaçırırsa sonraki çalışmada arayı otomatik doldurur (backfill).
- `.github/workflows/daily_update.yml` — her gün 06:00 (TR) script'i çalıştırıp CSV'yi commit eder.

## Kurulum (≈10 dk)

1. GitHub'da yeni bir repo aç (public en kolayı) ve bu klasördeki her şeyi push et:
   ```bash
   git init && git add . && git commit -m "init"
   git remote add origin https://github.com/KULLANICI/REPO.git
   git push -u origin main
   ```
2. Repo → Settings → Actions → General → "Workflow permissions" → **Read and write** seç.
3. Actions sekmesi → "Günlük veri üretimi" → **Run workflow** ile bir kez elle çalıştırıp test et.
4. Qlik Cloud'da **Web File** bağlantısı oluştur:
   `https://raw.githubusercontent.com/KULLANICI/REPO/main/data/fact.csv`
5. `qlik_load_script.qvs` içeriğini app'in Data Load Editor'üne yapıştır, connection adını düzelt, reload et.
6. App'e günlük reload schedule ekle: uygulama kartında **Reload > Schedule** → Daily → 07:00
   (Actions 06:00'da bittiği için güvenli).

## Ayarlar (generate_daily.py başında)

| Değişken | Anlamı | Mevcut |
|---|---|---|
| `CAMPAIGN_PROB` | Kampanyalı satır oranı | 0.72 |
| `NEW_CUSTOMER_PROB` | Yeni müşteri oranı | 0.52 |
| `REFUND_PROB` | Tam iade oranı | 0.085 |
| `MONTH_FACTOR` | Ay bazlı mevsimsellik çarpanları | Kasım/Aralık yüksek |

Not: Orijinal QVD'deki tarihler 2019-2021 aralığındaydı; demo canlı görünsün diye tüm geçmiş
7'nin katı gün ileri kaydırıldı (haftanın günü desenleri korunarak).
