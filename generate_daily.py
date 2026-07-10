#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FACT demo verisine her gün yeni, gerçekçi dummy satırlar ekler.

Mantık:
- data/fact.csv'nin son tarihinden bugüne kadar eksik her günü tek tek üretir (backfill destekli).
- Yeni günün satırları, geçmişteki AYNI AYIN satırlarından bootstrap örnekleme ile türetilir
  (dimension kombinasyonları -> bölge/şehir/ilçe/mağaza ve ürün hiyerarşisi her zaman tutarlı kalır,
  hiç var olmamış saçma kombinasyon üretilmez).
- Measure'lar şablon satırın değerinden rastgele gürültüyle türetilir: bazen artar, bazen düşer.
- Gün bazında da ayrı bir "gün faktörü" vardır (ay mevsimselliği + genel gürültü) -> bazı günler
  toplamda iyi geçer, bazı günler kötü.
- RNG tarih ile seed'lenir: aynı gün için script kaç kez çalışırsa çalışsın aynı veri üretilir
  ve aynı gün ikinci kez eklenmez (idempotent).
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

CSV_PATH = Path(__file__).parent / "data" / "fact.csv"
SEP = ";"
EPOCH = pd.Timestamp("1899-12-30")   # Qlik/Excel serial epoch

# --- Ayarlar ---------------------------------------------------------------
TARGET_END = date.today()            # bu tarihe kadar (dahil) üret
CAMPAIGN_PROB = 0.72                 # kampanyalı satır oranı (geçmiş: %71.7)
NEW_CUSTOMER_PROB = 0.52             # yeni müşteri oranı (geçmiş: %51.9)
REFUND_PROB = 0.085                  # tam iade oranı (geçmiş: %8.5, İade Tutar = Ciro)
MONTH_FACTOR = {                     # perakende mevsimselliği (görünür ama abartısız)
    1: 0.92, 2: 0.90, 3: 0.97, 4: 1.00, 5: 1.02, 6: 1.03,
    7: 0.98, 8: 0.97, 9: 1.02, 10: 1.05, 11: 1.15, 12: 1.12,
}
# ---------------------------------------------------------------------------

DIM_COLS = ["Bölge Adı", "Şehir", "İlçe", "Mağaza_2", "Mağaza", "Magaza_ID",
            "Ürün Ana Grubu", "Ürün Kategori", "Ürün Marka", "Ürün Adı", "Satış Tipi"]


def load_history() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, sep=SEP, encoding="utf-8-sig")
    df["Tarihnum"] = df["Tarihnum"].astype(int)
    return df


def day_factor(d: date, rng: np.random.Generator) -> float:
    """Günün genel performans çarpanı: mevsimsellik * gürültü. ~0.75-1.35 bandı."""
    noise = rng.lognormal(mean=0.0, sigma=0.12)          # bazen kötü gün, bazen iyi gün
    return MONTH_FACTOR[d.month] * float(np.clip(noise, 0.70, 1.45))


def generate_one_day(hist: pd.DataFrame, d: date) -> pd.DataFrame:
    rng = np.random.default_rng(seed=int(d.strftime("%Y%m%d")))  # idempotent
    factor = day_factor(d, rng)

    # --- Kaç satır üretilecek? Aynı ayın günlük satır dağılımından örnekle. ---
    hist_dates = pd.to_datetime(EPOCH) + pd.to_timedelta(hist["Tarihnum"], unit="D")
    same_month = hist[hist_dates.dt.month == d.month]
    pool = same_month if len(same_month) >= 500 else hist
    pool_dates = pd.to_datetime(EPOCH) + pd.to_timedelta(pool["Tarihnum"], unit="D")
    daily_counts = pool.groupby(pool_dates).size()
    n_rows = max(5, int(round(daily_counts.sample(1, random_state=rng.integers(1e9)).iloc[0] * factor)))

    # --- Şablon satırları örnekle (dimension tutarlılığı garantili) ---
    templates = pool.sample(n=n_rows, replace=True, random_state=int(rng.integers(1e9))).reset_index(drop=True)
    new = templates[DIM_COLS].copy()

    # --- Measure'lar: şablon * gürültü (artabilir de düşebilir de) ---
    ciro_noise = rng.lognormal(mean=0.0, sigma=0.28, size=n_rows)     # satır bazında ±%30 tipik salınım
    ciro = templates["Ciro"].to_numpy() * ciro_noise * factor
    ciro = np.round(np.clip(ciro, 2.0, None), 2)

    # Maliyet: şablonun maliyet/ciro oranına kendi gürültüsünü ekle -> marj bağımsız dalgalanır,
    # satış artarken kâr düşebilir (gerçekçi).
    cost_ratio = templates["Maliyet"].to_numpy() / np.maximum(templates["Ciro"].to_numpy(), 0.01)
    cost_ratio = np.clip(cost_ratio * rng.lognormal(0.0, 0.10, n_rows), 0.30, 2.20)
    maliyet = np.round(ciro * cost_ratio, 2)

    kar = np.round(ciro - maliyet, 2)
    kar_pct = np.round(kar / np.maximum(maliyet, 0.01), 4)

    miktar = np.maximum(0, np.round(
        templates["Miktar"].fillna(0).to_numpy() * rng.lognormal(0.0, 0.30, n_rows))).astype(int)

    hedef_ratio = np.clip(rng.normal(1.11, 0.45, n_rows), 0.0, 1.82)   # geçmiş Hedef/Ciro dağılımı
    hedef = np.round(ciro * hedef_ratio, 2)

    # --- Kampanya ---
    has_campaign = rng.random(n_rows) < CAMPAIGN_PROB
    camp_rows = hist[hist["Kampanya"].notna()]
    camp_sample = camp_rows.sample(n=n_rows, replace=True,
                                   random_state=int(rng.integers(1e9))).reset_index(drop=True)
    new["Kampanya"] = np.where(has_campaign, camp_sample["Kampanya"], None)
    new["Kampanya Sayısı"] = has_campaign.astype(int)
    new["Kampanya Tutarı"] = np.where(
        has_campaign,
        np.round(camp_sample["Kampanya Tutarı"].fillna(0).to_numpy()
                 * rng.lognormal(0.0, 0.15, n_rows), 2),
        0.0)
    ind = np.round(np.clip(camp_sample["İndirim Oranı"].fillna(0.55).to_numpy()
                           + rng.normal(0, 0.05, n_rows), 0.0, 0.93), 4)
    new["İndirim Oranı"] = np.where(has_campaign, ind, np.nan)

    # --- İade: küçük bir oranda tam iade (İade Tutar = Ciro) ---
    refund = rng.random(n_rows) < REFUND_PROB
    new["İade Tutar"] = np.where(refund, ciro, 0.0)

    # --- Müşteri ---
    is_new = (rng.random(n_rows) < NEW_CUSTOMER_PROB).astype(int)
    max_member = int(hist["MemberID"].max())
    new_ids = max_member + 1 + np.arange(n_rows)
    existing_ids = hist["MemberID"].sample(n=n_rows, replace=True,
                                           random_state=int(rng.integers(1e9))).to_numpy()
    new["MemberID"] = np.where(is_new == 1, new_ids, existing_ids).astype(int)
    new["Yeni Müşteri Sayı"] = is_new
    new["Yeni Müşteri %"] = is_new

    # --- Measure kolonları yaz ---
    new["Ciro"] = ciro
    new["Maliyet"] = maliyet
    new["Kâr"] = kar
    new["Kâr %"] = kar_pct
    new["Sepet Ortalaması"] = ciro          # geçmişte Sepet Ort. == Ciro
    new["Miktar"] = miktar
    new["Hedef"] = hedef

    # --- Tarih ve türev alanlar ---
    ts = pd.Timestamp(d)
    new["Tarih"] = ts.strftime("%Y-%m-%d")
    new["Tarihnum"] = (ts - EPOCH).days
    new["Yıl"] = ts.year
    new["Ay"] = ts.month
    new["AyNum"] = ts.month
    new["Yıl_Ay"] = ts.strftime("%Y-%m")
    new["Gun"] = ts.day
    new["Hafta"] = int(ts.isocalendar().week)
    new["Haftanıngunu"] = ts.dayofweek

    return new[hist.columns]   # kolon sırasını koru


def main() -> None:
    hist = load_history()
    last = (EPOCH + pd.Timedelta(days=int(hist["Tarihnum"].max()))).date()
    print(f"Mevcut son tarih: {last} | hedef: {TARGET_END}")

    added = []
    d = last + timedelta(days=1)
    while d <= TARGET_END:
        day_df = generate_one_day(hist, d)
        added.append(day_df)
        hist = pd.concat([hist, day_df], ignore_index=True)   # sonraki günler bunu da görsün
        print(f"  + {d}: {len(day_df)} satır (toplam ciro: {day_df['Ciro'].sum():,.0f})")
        d += timedelta(days=1)

    if not added:
        print("Eklenecek yeni gün yok, çıkılıyor.")
        return

    hist.to_csv(CSV_PATH, sep=SEP, index=False, encoding="utf-8-sig")
    total = sum(len(x) for x in added)
    print(f"Bitti: {len(added)} gün, {total} satır eklendi. Toplam: {len(hist)} satır.")


if __name__ == "__main__":
    main()
