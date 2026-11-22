# Profile, równoległość i pomiar kosztu

Ocena UZP to podmiana `./input` i uruchomienie CLI na zwykłym laptopie (i7, 16 GB, bez GPU), więc liczy się
jakość i koszt jednocześnie. Trzy pokrętła: **profil** (jakie komponenty działają), **`--workers`** (ile procesów) i
**`eval.bench`** (pomiar F1 kontra czas i pamięć).

## Profile

Profil to plik `profiles/<nazwa>.yaml`. Wybór: `--profile <nazwa>`, inaczej zmienna `ODW2JSON_PROFILE`, inaczej `ocr`.
Katalog profili można zmienić zmienną `ODW2JSON_PROFILES`.

| Profil | Co robi | Skany | Koszt |
|---|---|---|---|
| `text` | warstwa tekstowa PDF + receptury | dokument bez tekstu jest odrzucany (`{}`) | ułamki sekundy na dokument, ~160 MB |
| `ocr` (domyślny) | to samo + RapidOCR (ONNX, CPU) na stronach bez tekstu | czytane OCR-em | kilkanaście sekund na zeskanowaną stronę na zimno, wynik OCR trafia do cache |

Wynik profilu `ocr` jest identyczny z zachowaniem sprzed wprowadzenia profili (sprawdzone `git diff --no-index` na
42 PDF-ach).

Format pliku:

```yaml
description: jedna linijka
ocr: {enabled: true}      # OCR stron bez warstwy tekstowej
ingest: {dpi: 200}        # dowolna opcja PdfIngestor (ingest.dpi, ingest.cache, ingest.cache_dir, ingest.preprocess)
reader: null              # miejsce na lokalny model (T016)
```

`ingest.preprocess: none | levels` (domyślnie `levels`, zmienna `ODW2JSON_PREPROCESS` ma pierwszeństwo) czyści obraz strony
przed OCR (rozjaśnia przebijający tekst z drugiej strony skanu); strony z warstwą tekstową nie są dotykane, a ustawienie
wchodzi do klucza cache OCR.  Pomiar na 30 skanach UZP (pusty cache OCR): F1 0,9639 -> 0,9673, czas OCR +23%, mediana bez zmian.

Nieznany klucz albo nieznany `reader` kończy się błędem (`profile error`, kod wyjścia 2), a nie cichym użyciem innego
profilu.

### Profil `llm`

Trzeci profil (`profiles/llm.yaml`): to samo co `ocr` plus lokalny model Qwen3-1.7B (GGUF, CPU) dla pól, których
reguły nie odczytały. Włącza się świadomie (`--profile llm`), wagi pobiera się przy pierwszym użyciu. Opis, koszt
i gwarancje: [LLM.md](LLM.md). `eval.bench` liczy rozmiar modelu z `reader.model`.

## Równoległość: `--workers N`

`--workers N`, inaczej `ODW2JSON_WORKERS`, inaczej `min(4, liczba_rdzeni // 2)`. Pula procesów (`spawn`, działa na
Windows) rozdziela **dokumenty**, nie sprawy. Każdy proces buduje komponenty (OCR, receptury) raz. Plik zapisuje tylko
proces główny, w kolejności posortowanej, więc drzewo wyjściowe jest identyczne dla każdego `N` (sprawdza AC-2: `git diff
--no-index` out1 vs out4, oraz testy). Dokument, który się wywali, daje `{}` i wpis w logu; proces roboczy zabity
(np. brak pamięci) psuje tylko dokument, który wykonywał, resztę dokańcza się pojedynczo. `N` jest ograniczone liczbą
dokumentów. Ustawienia z kodu (`process_input` z własnymi komponentami) działają szeregowo.

W Dockerze: `ODW2JSON_PROFILE=text docker compose run --rm cli`, analogicznie `ODW2JSON_WORKERS`. W `start.bat` opcje
idą do CLI: `start.bat --profile text --workers 2`.

## Pomiar: `python -m eval.bench`

```
python -m eval.bench --profiles text,ocr --sets heldout,skany,negatywne --workers 1,4 --out .acc/bench
```

Zbiory: `dev` (przyklad_01–40), `heldout` (41–60), `skany` (30 skanów ze złotym JSON), `noisy` (drzewo z
`eval.make_noisy`, podaje się `--noisy-dir`), `negatywne` (12 dokumentów do odrzucenia). Dane UZP bierze z `uzp-data/`
(lub `UZP_DATA`, `--src`). Każdy zestaw (profil, zbiór, liczba procesów) to osobne uruchomienie CLI, więc szczytowa
pamięć (psutil, suma procesu głównego i wszystkich roboczych) nie miesza się między pomiarami.

Wyniki: `<out>/bench-<data>-<commit>.json` i `.md` oraz kopia historii w `<out>/history.csv`; do śledzonego `bench/history.csv` dopisują tylko `--record` i `--accept` (zwykłe uruchomienie, np. w CI, nie brudzi repo). Ostatnia linia:
`bench: <P> profiles x <S> sets ok`.

Jak czytać tabelę:

| Kolumna | Znaczenie |
|---|---|
| F1 exact / norm | miernik `eval/score.py` (dokładny i znormalizowany), mikro po polach |
| reject acc | dla `negatywne`: odsetek dokumentów z pustym wynikiem (`{}`), powinno być 100% |
| false rejects | dla pozostałych zbiorów: ile prawdziwych dokumentów dostało `{}` |
| p50 / p95 s | czas jednego dokumentu mierzony w procesie roboczym (przy kilku procesach rośnie przez rywalizację o CPU) |
| docs/min | liczba dokumentów przez czas całego uruchomienia (z ładowaniem modeli), to jest przepustowość |
| peak RSS MB | szczyt sumy pamięci wszystkich procesów |
| model MB | pliki modeli ładowane przez profil (ONNX OCR, ewentualnie model czytnika) |
| OCR cache | `warm`: wyniki OCR z cache (`%TEMP%/odw2json-ocr-cache`), czasy skanów nie oddają kosztu OCR; `cold` (`--cold`): świeży cache na każde uruchomienie |

Uwaga: przy `warm` model OCR nie jest nawet ładowany, więc pamięć skanów jest zaniżona. Do porównań kosztu skanów
używaj `--cold`.

### Bramka regresji

`--gate` porównuje wyniki z ostatnim wierszem `history.csv` oznaczonym `accepted=1` (ten sam profil, zbiór i liczba
procesów) i kończy się kodem 1, gdy: F1 (exact lub norm) na `heldout`/`skany` spada o więcej niż 0,005 albo p95 czasu lub
szczyt pamięci rosną o więcej niż 20% (wzrosty poniżej 0,05 s i 50 MB to szum i są pomijane). Wiersze dostają
`accepted=1` tylko z `--accept`, więc punkt odniesienia nie dryfuje po cichu:

```
python -m eval.bench --gate                 # sprawdź zmianę
python -m eval.bench --gate --accept        # sprawdź i przyjmij jako nowy punkt odniesienia
```

Gdy nie ma wiersza odniesienia, bramka przepuszcza. Dane UZP nie są w CI, więc bramka działa na maszynie właściciela.

## Domyślna liczba procesów

Pomiar na i7 (8 wątków) / 16 GB, szczegóły w raporcie T012: `--workers 4` daje 1,7 do 2,8 razy większą przepustowość niż
`--workers 1` przy szczycie pamięci ok. 0,5 GB dla tekstu i ok. 2,3 GB dla skanów czytanych OCR-em na zimno. Dlatego
domyślne `min(4, rdzenie // 2)` jest bezpieczne (daleko poniżej 8 GB). Każdy proces roboczy dostaje
`rdzenie // workers` wątków onnxruntime (zmienna `ODW2JSON_OCR_THREADS`), żeby cztery procesy nie konkurowały
czterdziestoma wątkami o osiem rdzeni. Pełny pomiar skanów na zimno (`bench/cold-ocr-2026-11-21.md`): ok. 6 s mediany
na dokument, 2,7 dok./min przy jednym procesie i 4,5 dok./min przy czterech.
