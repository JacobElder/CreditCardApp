# Credit Card Rewards Optimizer

A Streamlit app that picks the best credit card for a purchase category, including the quarterly 5% rotating categories (Chase Freedom Flex, Discover it).

## 🚀 Live App
Access the tool here: **[https://jakeeldercreditcardsrewards.streamlit.app/](https://jakeeldercreditcardsrewards.streamlit.app/)**

## ✨ Features
*   **Automatic rotating categories:** A scheduled GitHub Action reads each quarter's 5% categories from two independent sites, Doctor of Credit and Frequent Miler, merges them, and commits the result to `RotatingCategories.csv`. Streamlit Cloud redeploys on the commit. If either site breaks or posts late, the other still covers it.
*   **Honest comparisons:** Flat-rate cards (e.g. 2% on everything) are ranked alongside category bonuses, so a weak 3% category never beats a stronger everyday card.
*   **Point valuations you can switch:** Transferable points are valued with one of three presets: **Conservative** (default; [Frequent Miler's](https://frequentmiler.com/reasonable-redemption-values-rrvs/) median observed award values, e.g. Chase 1.5¢), **Optimistic** ([The Points Guy](https://thepointsguy.com/guide/monthly-valuations/), e.g. Chase 2.05¢), or **Cash** (1¢). When the best card changes between presets, the app says so. Edit `VALUATION_PRESETS` and `ENABLE_BOOSTS` in `rewards.py`.
*   **Citi Custom Cash analysis:** Shows where Custom Cash's 5% adds the most over your other cards.
*   **Mobile friendly:** Category chips wrap on small screens; the answer appears right under your choice.

## 📊 Data sources
| Data | Primary | Fallback |
|---|---|---|
| Fixed card rewards | Google Sheet, `Fixed` tab | `CreditCards.csv` |
| Rotating 5% categories | Google Sheet `Rotating` tab (manual overrides) → `RotatingCategories.csv` (auto-updated) | Live scrape of Doctor of Credit + Frequent Miler |

Rotating rows need **`Year` and `Quarter`** columns (e.g. `2026`, `4`). Rows without a year are ignored, because they would otherwise reappear in the same quarter every year. For each card, the highest-priority source with rows for the current quarter wins, so a Sheet entry fully replaces that card's scraped categories.

Category names are normalized (e.g. "Restaurants" → "Dining", "Grocery" → "Grocery Stores") via `CATEGORY_ALIASES` in `rewards.py`.

## 🔄 Updating rotating categories
This runs daily on its own via `.github/workflows/update-rotating.yml`. To run it by hand:

```bash
python rotating_scraper.py                 # current + next quarter
python rotating_scraper.py --quarter 2027-1
python rotating_scraper.py --quarter 2026-4 --force   # re-scrape an existing quarter
```

You can also trigger it from the repo's **Actions** tab (**Update rotating categories** → **Run workflow**).

The `Source` column records which site reported each row. The updater keeps re-checking a quarter until both sites have contributed. If you edit a quarter by hand, set `Source` to `manual` (or leave it blank) and the updater will leave that quarter alone unless you pass `--force`.

The run fails and GitHub emails you in two cases: the current quarter has no data, or a site's layout changed and its parser needs updating. The parsers live in `rotating_scraper.py` (`DoctorOfCredit`, `FrequentMiler`).

## 🛠️ Development
```bash
pip install -r requirements-dev.txt
python -m pytest
streamlit run streamlitCards.py
```

*   `rewards.py`: data cleaning, category normalization, valuation, and ranking (no Streamlit, fully tested)
*   `rotating_scraper.py`: Doctor of Credit and Frequent Miler parsers, plus the CSV updater
*   `streamlitCards.py`: the UI
