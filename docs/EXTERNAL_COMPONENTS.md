# Komponenty zewnętrzne i licencje

Regulamin §4.1: wymieniamy wszystkie komponenty firm trzecich. Wszystkie są open source na licencjach
permisywnych. **Rozwiązanie nie używa żadnego komponentu na licencji AGPL ani GPL** (świadomie odrzucone:
PyMuPDF i Ghostscript na AGPL, modele spaCy `pl_core_news_*` na GPL). Nie używa też modeli językowych ani usług
w chmurze. Wszystko działa lokalnie na CPU.

Wersje: minimalne z `requirements.txt` / wersje przetestowane (venv Python 3.13.2, 2026-11-21).
Źródło weryfikacji licencji: raport `licences.md` zespołu (strony projektów) oraz metadane pakietów;
pozycje oznaczone „(metadane)” nie były osobno sprawdzane na stronie projektu.

## Biblioteki Pythona (bezpośrednie, `requirements.txt`)
| Komponent | Wersja | Licencja | Do czego | Link |
|---|---|---|---|---|
| pdfplumber | 0.11.4 | MIT | tekst i słowa z ramkami z warstwy tekstowej PDF | https://github.com/jsvine/pdfplumber |
| PyYAML | ≥6.0 (6.0.4) | MIT (metadane) | wczytywanie receptur i słowników | https://github.com/yaml/pyyaml |
| jsonschema | ≥4.23 (4.26.0) | MIT (metadane) | walidacja receptur (`recipes/recipe.schema.json`) | https://github.com/python-jsonschema/jsonschema |
| pypdfium2 | ≥4.30 (5.15.2) | Apache-2.0 lub BSD-3-Clause; PDFium: BSD-3-Clause + licencje zależności dołączone do koła | render stron do OCR | https://github.com/pypdfium2-team/pypdfium2 |
| RapidOCR | ≥3.10 (3.10.0) | Apache-2.0 | OCR skanów | https://github.com/RapidAI/RapidOCR |
| Modele RapidOCR (PP-OCR, ONNX) | z pakietu RapidOCR | Apache-2.0 (pochodne PaddleOCR) | detekcja i rozpoznawanie tekstu | https://github.com/PaddlePaddle/PaddleOCR |
| ONNX Runtime | ≥1.20 (1.32.0) | MIT (metadane) | wykonanie modeli OCR na CPU | https://github.com/microsoft/onnxruntime |
| opencv-python-headless | ≥4.10,<5 (4.14.0) | Apache-2.0 (OpenCV); koła Linux zawierają FFmpeg na LGPL-2.1 (biblioteka dynamiczna, nieużywana przez nas) | przetwarzanie obrazu w OCR | https://github.com/opencv/opencv-python |
| NumPy | ≥1.26 (2.5.5) | BSD-3-Clause (metadane) | obrazy jako tablice | https://github.com/numpy/numpy |
| Pillow | ≥10.0 (13.0.0) | MIT-CMU (HPND) (metadane) | obrazy, zaszumianie zbioru testowego | https://github.com/python-pillow/Pillow |
| FastAPI | ≥0.115 (0.165.0) | MIT | API i interfejs webowy | https://github.com/fastapi/fastapi |
| Uvicorn | ≥0.30 (0.54.0) | BSD-3-Clause (metadane) | serwer HTTP | https://github.com/encode/uvicorn |
| python-multipart | ≥0.0.9 (0.0.34) | Apache-2.0 (metadane) | wgrywanie plików | https://github.com/Kludex/python-multipart |
| HTTPX | ≥0.27 (0.28.1) | BSD-3-Clause (metadane) | klient testowy API | https://github.com/encode/httpx |

## Zależności pośrednie (najważniejsze)
| Komponent | Licencja | Ściągany przez |
|---|---|---|
| pdfminer.six | MIT | pdfplumber |
| Starlette | BSD-3-Clause (metadane) | FastAPI |
| Pydantic | MIT | FastAPI |
| Shapely | BSD-3-Clause (metadane) | RapidOCR |
| pyclipper | MIT (metadane) | RapidOCR |

## Interfejs webowy (pliki w repozytorium)
| Komponent | Licencja | Gdzie |
|---|---|---|
| Font **Anybody** (wdth 50–150, wght 100–900, latin + latin-ext) | SIL Open Font License 1.1 | `web/static/coldtrace/fonts/anybody-*.woff2` (https://fonts.google.com/specimen/Anybody) |
| Font **Martian Mono** (wdth 75–112.5, wght 100–800, latin + latin-ext) | SIL Open Font License 1.1 | `web/static/coldtrace/fonts/martian-mono-*.woff2` (https://fonts.google.com/specimen/Martian+Mono) |
| System wizualny Cold Trace i logo Eterphis | własny projekt zespołu (nie komponent zewnętrzny) | `web/static/coldtrace/`, źródło `design/cold-trace/` |

Fonty są hostowane lokalnie, więc interfejs działa bez internetu.

## Środowisko uruchomieniowe
| Komponent | Licencja | Uwagi |
|---|---|---|
| Python 3.13 | PSF License | interpreter |
| Obraz Docker `python:3.13-slim` | PSF + pakiety Debiana (licencje wolne) | baza obrazu; doinstalowane `libglib2.0-0` (LGPL-2.1), `libgomp1` (GPL-3.0 z wyjątkiem GCC Runtime Library Exception, który pozwala na użycie w dowolnym programie) jako biblioteki systemowe dla OpenCV/ONNX Runtime |

## Narzędzia tylko dla zespołu (nie są częścią rozwiązania)
`house/` (narzędzia pracy zespołu), GitHub Actions (CI). Nie trafiają do obrazu Docker (`.dockerignore`).
