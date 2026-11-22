# Lokalny model językowy (profil `llm`)

Opis wykorzystanego LLM wymagany przez README konkursu. Krótko: **rdzeń ekstrakcji działa bez żadnego modelu**
(reguły YAML, F1 liczone lokalnie); profil `llm` jest opcją, która dokłada do tego mały model uruchamiany **lokalnie na
CPU** i czyta tylko te pola, których reguły nie odczytały. Domyślny profil to `ocr`; `llm` włącza się świadomie
(`--profile llm` albo `ODW2JSON_PROFILE=llm`).

## Model

| | |
|---|---|
| Model | **Qwen3-1.7B**, kwantyzacja Q8_0, plik GGUF (`Qwen/Qwen3-1.7B-GGUF`) |
| Licencja | Apache-2.0 (model i runtime) |
| Rozmiar | 1,7 mld parametrów, plik 1,83 GB, około 2,9 GB RAM po załadowaniu |
| Runtime | llama.cpp (MIT) przez `llama-cpp-python` (MIT): gotowe koło dla Windows/Python 3.13, bez kompilatora, tylko CPU |
| Sieć | tylko jednorazowe pobranie wag; potem działa całkowicie offline. Żadne dane nie opuszczają maszyny |

Wybór (pomiary własne zespołu): sprawdzono Qwen3 0,6B / 1,7B / 4B i Bielik 1,5B v3 (wszystkie
Apache-2.0). Najlepszy na naszych słabych polach był Qwen3-1.7B (15/25 pytań poprawnie, wszystkie cytaty w tekście);
0,6B zmyśla, 4B nie jest lepszy, a potrzebuje 5 GB.

Wagi nie są w repozytorium. Pobranie: `python -m odw2json.llm.fetch` (suma sha256 sprawdzana, plik trafia do `models/`);
przy pierwszym uruchomieniu profilu `llm` CLI robi to samo samo, jeśli pliku brakuje (wyłącza to `fetch: false` w
profilu). Obraz Docker: argument budowania `LLM_MODEL=qwen3-1.7b` wkłada wagi do obrazu (patrz `Dockerfile`).
Brak wag, brak pakietu `llama-cpp-python` albo brak sieci przy pierwszym pobraniu **nie psuje przebiegu**: wynik jest
wtedy taki sam jak w profilu `ocr`.

## Co model robi, a czego nigdy

Zasady (wzorzec z `spec-extraction` właściciela repo):

1. **Przepisuje, nie liczy.** Model zwraca napisy tak, jak są wydrukowane (JSON ze schematem wymuszonym gramatyką;
   każde pole może być `null`). Daty, NIP-y, kwoty i identyfikatory robią z nich normalizatory z receptury, a
   walidatory (NIP, PESEL, IBAN) sprawdzają sumy kontrolne.
2. **Ugruntowanie.** Każda wartość przychodzi z cytatem. Cytat musi się znaleźć w tekście strony, którą model widział
   (porównanie na szkielecie: małe litery, bez diakrytyków, tylko litery i cyfry), a sama wartość musi być częścią
   swojego cytatu. Wartość bez znalezionego cytatu jest odrzucana i zapisana w śladzie. Dowód w wyniku ma regułę
   `llm:<model>`, stronę, fragment tekstu i niską pewność (0,8; 0,4 gdy suma kontrolna się nie zgadza).
3. **Nie nadpisuje.** Wartość odczytana przez regułę z pełną pewnością nigdy nie jest zastępowana. Model uzupełnia
   pola puste i o niskiej pewności; wartości o pewności poniżej 1,0 (odczyt OCR) tylko na polach z `override: true`.
   Brak wartości w dokumencie zostaje `null`: nic nie jest brane z innego dokumentu.
4. **Pyta tylko, gdy trzeba.** Jeśli nic nie wymaga uzupełnienia (albo wyrażenie `when:` nie pasuje do tekstu), model
   w ogóle się nie uruchamia. Kontekst to pierwsze strony (domyślnie 2, do 6000 znaków), nie cały dokument.

## Konfiguracja, nie kod

Pole receptury włącza czytnik blokiem `llm:` (albo blok na poziomie klasy). Pytania budowane są z receptury; w
`odw2json/llm/` i w silniku nie ma nazw klas dokumentów. Nowa klasa dostaje pomoc modelu samym YAML-em, składnia w
[ADDING_A_DOCUMENT_CLASS.md](ADDING_A_DOCUMENT_CLASS.md#czytelnik-llm-llm-opcjonalny). Dziś opt-in mają: PESEL-e
pełnomocników (lista osób), numer BZP, numer postępowania, nazwy stron odwołania, powód zaskarżonej czynności (wybór z
12 pozycji słownika) i tytuł przelewu.

Ślad decyzji (co wypełniono, co odrzucono i dlaczego): zmienna `ODW2JSON_LLM_TRACE=<plik.jsonl>`.

## Koszt i pomiar

Na naszym laptopie testowym (i5-1035G1, 4 rdzenie, współdzielony z innymi zadaniami) model 1,7B daje około 12 tokenów
promptu na sekundę, więc jedno wywołanie na 1-2 stronach to 1-3 minuty. Dlatego wywołań jest mało (kilka na 60
dokumentów) i profil `llm` nie jest domyślny. Aktualną tabelę F1/czas/RAM dla `ocr` kontra `llm` daje
`python -m eval.bench --profiles ocr,llm ...` (opis w [PROFILES.md](PROFILES.md)).
