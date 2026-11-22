"""Generate a varied synthetic benchmark: KIO appeal cases with gold JSON, born-digital and scanned.

    python -m eval.make_synth --out <dir> [--cases 20] [--seed 2026] [--scan-share 0.35]

Writes ``<out>/input/synth_NN/*.pdf``, ``<out>/gold/synth_NN/*.json`` and ``<out>/manifest.json`` (per document:
class, layout, font, scan mode). Every case is a set of documents as they come in a real filing: the appeal, zero to
two powers of attorney, one or two bank transfer confirmations, sometimes a document outside the three classes (no
gold, must come out as ``{}``). File names do not reveal the class.

Variety is the point. Layouts follow public templates (UZP appeal template, the KIO power-of-attorney template with
its individual / company / consortium versions, real appeals published on contracting authorities' BIP pages, the
look of Polish bank confirmations) and are drawn round-robin so every layout appears. Fonts, margins, date and number
formats (NIP with dashes, BZP with spaces, IBAN with or without PL), the order of the header blocks, declined names
(``radcę prawnego Tomasza Nowaka``), distractor parties and dates, e-signature stamps, footers all vary per document.
Banks, companies, people and numbers are fictitious (valid checksums, made-up names).

Gold follows the UZP conventions in ``oczekiwane-json``: names in the nominative as printed, NIP/REGON/KRS digits,
BZP without spaces, TED as NNNNNN-YYYY, consortium = its leader in ``Odwolujacy``, account numbers as digits on
text-layer documents and as printed (with PL when printed) on scans.

Scan modes (image-only PDF): office (eval.make_noisy), fax (binarised, low vertical resolution, fax header line),
copy (grey photocopy, edge shadow, punch holes) and phone (colour photo, vignette, slight perspective).
Needs reportlab (BSD) and the system TTF fonts (Windows fonts dir or $FONTS_DIR). Output stays outside the repo.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from eval import make_noisy

UZP_ACCOUNT = "60101010100081362231000000"
MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
          "października", "listopada", "grudnia"]

# ------------------------------------------------------------------------------------------------ fonts

FONT_FILES = {
    "Arial": ("arial.ttf", "arialbd.ttf"), "Times": ("times.ttf", "timesbd.ttf"),
    "Calibri": ("calibri.ttf", "calibrib.ttf"), "Georgia": ("georgia.ttf", "georgiab.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf"), "Tahoma": ("tahoma.ttf", "tahomabd.ttf"),
    "CourierNew": ("cour.ttf", "courbd.ttf"), "ArialNarrow": ("ARIALN.TTF", "ARIALNB.TTF"),
}
FONTS: list[str] = []


def fonts_dir() -> Path:
    env = os.environ.get("FONTS_DIR")
    for d in ([Path(env)] if env else []) + [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/msttcorefonts")]:
        if d.is_dir():
            return d
    raise SystemExit("no TTF fonts found: set FONTS_DIR")


def register_fonts() -> None:
    if FONTS:
        return
    d = fonts_dir()
    for name, (reg, bold) in FONT_FILES.items():
        if (d / reg).is_file() and (d / bold).is_file():
            pdfmetrics.registerFont(TTFont(name, str(d / reg)))
            pdfmetrics.registerFont(TTFont(name + "-B", str(d / bold)))
            pdfmetrics.registerFontFamily(name, normal=name, bold=name + "-B", italic=name, boldItalic=name + "-B")
            FONTS.append(name)
    if not FONTS:
        raise SystemExit("none of the expected TTF fonts found in " + str(d))


# ------------------------------------------------------------------------------------------------ numbers

def nip(r: random.Random) -> str:
    while True:
        d = [r.randint(1, 9)] + [r.randint(0, 9) for _ in range(8)]
        c = sum(a * b for a, b in zip(d, (6, 5, 7, 2, 3, 4, 5, 6, 7))) % 11
        if c != 10:
            return "".join(map(str, d)) + str(c)


def regon(r: random.Random) -> str:
    d = [r.randint(0, 9) for _ in range(8)]
    c = sum(a * b for a, b in zip(d, (8, 9, 2, 3, 4, 5, 6, 7))) % 11 % 10
    return "".join(map(str, d)) + str(c)


def krs(r: random.Random) -> str:
    return "0000" + f"{r.randint(10000, 999999):06d}"


def pesel(r: random.Random, female: bool) -> str:
    y, m, d = r.randint(1958, 1998), r.randint(1, 12), r.randint(1, 28)
    s = r.randint(0, 999)
    sex = r.choice([0, 2, 4, 6, 8]) if female else r.choice([1, 3, 5, 7, 9])
    digits = [int(x) for x in f"{y % 100:02d}{m:02d}{d:02d}{s:03d}{sex}"]
    c = (10 - sum(a * b for a, b in zip(digits, (1, 3, 7, 9, 1, 3, 7, 9, 1, 3))) % 10) % 10
    return "".join(map(str, digits)) + str(c)


def nrb(r: random.Random, bank: str | None = None) -> str:
    bank = bank or f"{r.randint(1020, 2490):04d}{r.randint(0, 9999):04d}"
    acct = "".join(str(r.randint(0, 9)) for _ in range(16))
    rest = bank + acct
    check = 98 - int(rest + "252100") % 97
    return f"{check:02d}{rest}"


def fmt_nip(v: str, style: int) -> str:
    return [v, f"{v[:3]}-{v[3:6]}-{v[6:8]}-{v[8:]}", f"{v[:3]} {v[3:6]} {v[6:8]} {v[8:]}", f"{v[:3]}-{v[3:5]}-{v[5:7]}-{v[7:]}"][style]


def fmt_acct(v: str, style: int) -> str:
    """0: PL + groups, 1: groups, 2: plain digits, 3: PL + plain."""
    groups = v[:2] + " " + " ".join(v[i:i + 4] for i in range(2, 26, 4))
    return ["PL" + groups, groups, v, "PL" + v][style]


def acct_gold(v: str, style: int, scanned: bool) -> str:
    return ("PL" + v) if (scanned and style in (0, 3)) else v


def fmt_amount(v: float, style: int) -> str:
    whole, frac = f"{v:.2f}".split(".")
    sp = f"{int(whole):,}".replace(",", " ")
    dot = f"{int(whole):,}".replace(",", ".")
    return [f"{sp},{frac} PLN", f"{dot},{frac} zł", f"PLN {sp},{frac}", f"{whole},{frac}", f"-{sp},{frac} PLN",
            f"{sp},{frac} zł"][style]


def fmt_date(d: dt.date, style: int) -> str:
    return [f"{d.day} {MONTHS[d.month - 1]} {d.year} r.", f"{d:%d.%m.%Y} r.", f"{d:%d.%m.%Y}", f"{d:%Y-%m-%d}",
            f"{d.day} {MONTHS[d.month - 1]} {d.year} roku", f"{d.day:02d} {MONTHS[d.month - 1]} {d.year} r."][style]


def fmt_bank_date(d: dt.date, style: int) -> str:
    return [f"{d:%Y-%m-%d}", f"{d:%d.%m.%Y}", f"{d:%d-%m-%Y}", f"{d:%d/%m/%Y}"][style]


# ------------------------------------------------------------------------------------------------ people

MALE = [("Tomasz", "Tomasza", "Tomaszowi"), ("Piotr", "Piotra", "Piotrowi"), ("Marek", "Marka", "Markowi"),
        ("Paweł", "Pawła", "Pawłowi"), ("Michał", "Michała", "Michałowi"), ("Krzysztof", "Krzysztofa", "Krzysztofowi"),
        ("Andrzej", "Andrzeja", "Andrzejowi"), ("Łukasz", "Łukasza", "Łukaszowi"), ("Grzegorz", "Grzegorza", "Grzegorzowi"),
        ("Rafał", "Rafała", "Rafałowi"), ("Wojciech", "Wojciecha", "Wojciechowi"), ("Jakub", "Jakuba", "Jakubowi"),
        ("Maciej", "Macieja", "Maciejowi"), ("Adam", "Adama", "Adamowi"), ("Bartosz", "Bartosza", "Bartoszowi"),
        ("Kamil", "Kamila", "Kamilowi"), ("Mateusz", "Mateusza", "Mateuszowi"), ("Jan", "Jana", "Janowi")]
FEMALE = [("Anna", "Annę", "Annie"), ("Katarzyna", "Katarzynę", "Katarzynie"), ("Magdalena", "Magdalenę", "Magdalenie"),
          ("Agnieszka", "Agnieszkę", "Agnieszce"), ("Joanna", "Joannę", "Joannie"), ("Monika", "Monikę", "Monice"),
          ("Ewa", "Ewę", "Ewie"), ("Małgorzata", "Małgorzatę", "Małgorzacie"), ("Barbara", "Barbarę", "Barbarze"),
          ("Aleksandra", "Aleksandrę", "Aleksandrze"), ("Karolina", "Karolinę", "Karolinie"), ("Natalia", "Natalię", "Natalii"),
          ("Beata", "Beatę", "Beacie"), ("Dorota", "Dorotę", "Dorocie"), ("Justyna", "Justynę", "Justynie"),
          ("Iwona", "Iwonę", "Iwonie")]
SURNAMES = ["Nowak", "Kowalski", "Wiśniewski", "Wójcik", "Kamiński", "Lewandowski", "Zieliński", "Szymański",
            "Woźniak", "Dąbrowski", "Kozłowski", "Jankowski", "Mazur", "Kwiatkowski", "Krawczyk", "Piotrowski",
            "Grabowski", "Pawlak", "Michalski", "Król", "Wieczorek", "Jabłoński", "Wróbel", "Nowicki", "Majewski",
            "Olszewski", "Stępień", "Malinowski", "Jaworski", "Adamczyk", "Dudek", "Pietrzak", "Wilk", "Kaczmarek",
            "Zając", "Baran", "Urban", "Rutkowski", "Sadowski", "Czarnecki", "Ostrowski", "Brzeziński", "Głowacki",
            "Laskowski", "Ziółkowski", "Kubiak", "Szczepański", "Górecki", "Witkowski", "Sobczak"]
IRREG = {"Wróbel": ("Wróbla", "Wróblowi"), "Kaczmarek": ("Kaczmarka", "Kaczmarkowi"), "Dudek": ("Dudka", "Dudkowi"),
         "Stępień": ("Stępnia", "Stępniowi"), "Zając": ("Zająca", "Zającowi"), "Król": ("Króla", "Królowi"),
         "Wieczorek": ("Wieczorka", "Wieczorkowi"), "Sobczak": ("Sobczaka", "Sobczakowi")}


def surname_forms(s: str, female: bool) -> tuple[str, str, str]:
    if s.endswith(("ski", "cki")):
        base = s[:-1]
        return (base + "a", base + "ą", base + "iej") if female else (s, base + "iego", base + "iemu")
    if female:
        return (s, s, s)
    if s in IRREG:
        return (s,) + IRREG[s]
    return (s, s + "a", s + "owi")


@dataclass
class Person:
    first: tuple
    last: tuple
    female: bool
    pesel: str
    title: str = ""          # "r. pr." / "adw." / "apl. radc." / ""

    @property
    def nom(self) -> str:
        return f"{self.first[0]} {self.last[0]}"

    @property
    def acc(self) -> str:
        return f"{self.first[1]} {self.last[1]}"

    @property
    def dat(self) -> str:
        return f"{self.first[2]} {self.last[2]}"

    def title_acc(self) -> str:
        if self.title == "r. pr.":
            return "radcę prawnego"
        if self.title == "adw.":
            return "adwokat" if self.female else "adwokata"
        if self.title == "apl. radc.":
            return "aplikantkę radcowską" if self.female else "aplikanta radcowskiego"
        return "Panią" if self.female else "Pana"

    def title_long(self) -> str:
        return {"r. pr.": "radca prawny", "adw.": "adwokat", "apl. radc.": "aplikant radcowski"}.get(self.title, "")


def person(r: random.Random, used: set, title: str = "") -> Person:
    while True:
        female = r.random() < 0.45
        first = r.choice(FEMALE if female else MALE)
        last = surname_forms(r.choice(SURNAMES), female)
        if (first[0], last[0]) not in used:
            used.add((first[0], last[0]))
            return Person(first, last, female, pesel(r, female), title)


# ------------------------------------------------------------------------------------------------ places, entities

TOWNS = [("Kraków", "w Krakowie"), ("Warszawa", "w Warszawie"), ("Poznań", "w Poznaniu"), ("Wrocław", "we Wrocławiu"),
         ("Gdańsk", "w Gdańsku"), ("Łódź", "w Łodzi"), ("Lublin", "w Lublinie"), ("Rzeszów", "w Rzeszowie"),
         ("Białystok", "w Białymstoku"), ("Kielce", "w Kielcach"), ("Olsztyn", "w Olsztynie"), ("Opole", "w Opolu"),
         ("Toruń", "w Toruniu"), ("Bydgoszcz", "w Bydgoszczy"), ("Katowice", "w Katowicach"), ("Szczecin", "w Szczecinie"),
         ("Zielona Góra", "w Zielonej Górze"), ("Radom", "w Radomiu"), ("Płock", "w Płocku"), ("Tarnów", "w Tarnowie"),
         ("Nowy Sącz", "w Nowym Sączu"), ("Elbląg", "w Elblągu"), ("Legnica", "w Legnicy"), ("Siedlce", "w Siedlcach"),
         ("Gniezno", "w Gnieźnie"), ("Zamość", "w Zamościu"), ("Przemyśl", "w Przemyślu"), ("Suwałki", "w Suwałkach"),
         ("Konin", "w Koninie"), ("Piła", "w Pile"), ("Ostrołęka", "w Ostrołęce"), ("Chełm", "w Chełmie")]
STREETS = ["ul. Lipowa", "ul. Polna", "ul. Leśna", "ul. Słoneczna", "ul. Krótka", "ul. Szkolna", "ul. Ogrodowa",
           "ul. Kościuszki", "al. Jana Pawła II", "ul. Mickiewicza", "ul. Przemysłowa", "ul. Fabryczna", "ul. Kolejowa",
           "ul. 3 Maja", "ul. Piłsudskiego", "ul. Sienkiewicza", "al. Solidarności", "ul. Wojska Polskiego",
           "ul. Grunwaldzka", "ul. Towarowa", "ul. Rzemieślnicza", "pl. Wolności", "ul. Zielona", "ul. Batorego"]
ROOT_A = ["Ter", "Nor", "Vel", "Kar", "Mal", "Sol", "Bal", "Ast", "Dor", "Gral", "Lum", "Kor", "Wis", "Tor", "Hel",
          "Dru", "Fen", "Mir", "Zen", "Arg", "Om", "Rad", "Sil", "Bor", "Kal", "Ven", "Pro", "Ekso", "Inter", "Geo"]
ROOT_B = ["dex", "tron", "bud", "mar", "vex", "lan", "med", "tech", "plan", "pol", "sys", "net", "gaz", "kom",
          "trans", "eko", "max", "tor", "ing", "stal", "mont", "data", "san", "pak"]
SECTORS = ["Budownictwo", "Infrastruktura", "Systemy Informatyczne", "Medical", "Serwis", "Logistyka", "Energetyka",
           "Drogi i Mosty", "Instalacje", "Technologie", "Facility Services", "Automatyka", "Ekologia", "Konstrukcje",
           "Inżynieria", "Solutions", "Dystrybucja", "Usługi Komunalne", ""]
FORMS = {
    "spzoo": ["sp. z o.o.", "Sp. z o.o.", "spółka z ograniczoną odpowiedzialnością", "Spółka z o.o."],
    "sa": ["S.A.", "spółka akcyjna", "Spółka Akcyjna"],
    "spk": ["sp. k.", "sp.k.", "spółka komandytowa", "sp. z o.o. sp.k."],
    "spj": ["sp. j.", "sp.j.", "spółka jawna"],
}
JDG_TRADES = ["Przedsiębiorstwo Usługowo-Handlowe", "Zakład Remontowo-Budowlany", "Usługi Transportowe",
              "Firma Handlowa", "Pracownia Projektowa", "Usługi Informatyczne", "P.H.U."]


@dataclass
class Entity:
    kind: str                 # spzoo/sa/spk/spj/jdg/public
    name: str                 # canonical name (as in the appeal)
    alt_name: str             # same entity written with the long legal form (for the power of attorney)
    street: str
    town: tuple
    postcode: str
    nip: str
    regon: str
    krs: str | None
    email: str
    owner: Person | None = None
    signers: list = field(default_factory=list)   # [(Person, function)]

    @property
    def address(self) -> str:
        return f"{self.street}, {self.postcode} {self.town[0]}"


def _slug(s: str) -> str:
    tr = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ ", "acelnoszzACELNOSZZ-")
    return "".join(ch for ch in s.translate(tr).lower() if ch.isalnum() or ch == "-").strip("-")[:18]


def company(r: random.Random, kind: str, used: set, used_names: set) -> Entity:
    while True:
        root = r.choice(ROOT_A) + r.choice(ROOT_B)
        if r.random() < 0.3:
            root = root.upper()
        sector = r.choice(SECTORS)
        core = f"{root} {sector}".strip()
        if core not in used_names:
            used_names.add(core)
            break
    town = r.choice(TOWNS)
    pc = f"{r.randint(0, 99):02d}-{r.randint(0, 999):03d}"
    street = f"{r.choice(STREETS)} {r.randint(1, 180)}" + (f"/{r.randint(1, 40)}" if r.random() < 0.3 else "")
    if kind == "jdg":
        owner = person(r, used)
        trade = r.choice(JDG_TRADES)
        root_q = r.choice([f"„{root.upper()}”", root.upper(), f"{root.upper()}-BUD"])
        name = f"{trade} {root_q} {owner.nom}" if r.random() < 0.5 else f"{root_q.strip('„”')} {owner.nom}"
        e = Entity(kind, name, name, street, town, pc, nip(r), regon(r), None,
                   f"biuro@{_slug(root)}.example", owner=owner)
        e.signers = [(owner, "właściciel")]
        return e
    forms = FORMS[kind]
    short = r.choice(forms[:2])
    long_ = forms[2] if len(forms) > 2 else short
    name, alt = f"{core} {short}", f"{core} {long_}"
    e = Entity(kind, name, alt, street, town, pc, nip(r), regon(r) if r.random() < 0.6 else regon(r) + f"{r.randint(0, 99999):05d}",
               krs(r), f"{r.choice(['biuro', 'sekretariat', 'office', 'kontakt', 'przetargi'])}@{_slug(root)}.example")
    funcs = {"spzoo": ["Prezes Zarządu", "Członek Zarządu", "Prokurent", "Wiceprezes Zarządu"],
             "sa": ["Prezes Zarządu", "Członek Zarządu", "Wiceprezes Zarządu", "Prokurent"],
             "spk": ["Komplementariusz", "Prokurent", "Prezes Zarządu Komplementariusza"],
             "spj": ["Wspólnik", "Wspólnik"]}[kind]
    for i in range(r.choice([1, 1, 2, 2, 3]) if kind != "spj" else 2):
        e.signers.append((person(r, used), funcs[min(i, len(funcs) - 1)] if i else funcs[0]))
    return e


PUBLIC = [
    ("Gmina {T}", False), ("Miasto {T}", False), ("Szpital Wojewódzki im. Jana Pawła II {L}", False),
    ("Zarząd Dróg Wojewódzkich {L}", False), ("Samodzielny Publiczny Zakład Opieki Zdrowotnej {L}", False),
    ("Miejskie Przedsiębiorstwo Wodociągów i Kanalizacji {L} sp. z o.o.", True), ("Politechnika {A}", False),
    ("Zarząd Transportu Miejskiego {L}", False), ("Powiatowe Centrum Medyczne {L}", False),
    ("Regionalny Zarząd Gospodarki Wodnej {L}", False), ("Komenda Wojewódzka Policji {L}", False),
    ("Uniwersytet Medyczny {L}", False), ("Zakład Gospodarki Komunalnej {L} sp. z o.o.", True),
    ("Miejski Ośrodek Sportu i Rekreacji {L}", False), ("Zespół Szkół Technicznych {L}", False),
    ("Centrum Usług Wspólnych {L}", False), ("Wojewódzki Fundusz Ochrony Środowiska {L}", False),
]
TOWN_ADJ = {"Kraków": "Krakowska", "Warszawa": "Warszawska", "Poznań": "Poznańska", "Wrocław": "Wrocławska",
            "Gdańsk": "Gdańska", "Łódź": "Łódzka", "Lublin": "Lubelska", "Rzeszów": "Rzeszowska", "Białystok": "Białostocka",
            "Kielce": "Świętokrzyska", "Opole": "Opolska", "Bydgoszcz": "Bydgoska", "Katowice": "Śląska",
            "Szczecin": "Szczecińska", "Toruń": "Toruńska", "Radom": "Radomska", "Olsztyn": "Olsztyńska"}


def public_entity(r: random.Random, used_names: set) -> Entity:
    while True:
        tpl, has_krs = r.choice(PUBLIC)
        town = r.choice(TOWNS)
        if "{A}" in tpl and town[0] not in TOWN_ADJ:
            continue
        name = tpl.replace("{T}", town[0]).replace("{L}", town[1]).replace("{A}", TOWN_ADJ.get(town[0], ""))
        if name not in used_names:
            used_names.add(name)
            break
    pc = f"{r.randint(0, 99):02d}-{r.randint(0, 999):03d}"
    return Entity("public", name, name, f"{r.choice(STREETS)} {r.randint(1, 90)}", town, pc, nip(r), regon(r),
                  krs(r) if has_krs else None, f"{r.choice(['zamowienia', 'zp', 'przetargi', 'dzp'])}@{_slug(name)}.example")


TITLES = {
    "roboty": ["Przebudowa drogi powiatowej nr {n}R wraz z budową chodnika", "Termomodernizacja budynku Szkoły Podstawowej nr {k}",
               "Budowa sieci kanalizacji sanitarnej w miejscowości {T}", "Rozbudowa oddziału ratunkowego wraz z lądowiskiem",
               "Budowa hali sportowej przy Zespole Szkół nr {k}", "Remont mostu w ciągu drogi wojewódzkiej nr {n}",
               "Przebudowa stacji uzdatniania wody w {T}", "Budowa ścieżki rowerowej wzdłuż rzeki — etap {k}"],
    "dostawy": ["Dostawa tomografu komputerowego wraz z instalacją", "Dostawa sprzętu komputerowego i oprogramowania biurowego",
                "Dostawa autobusów elektrycznych wraz z infrastrukturą ładowania", "Dostawa leków i wyrobów medycznych — {k} pakietów",
                "Zakup i dostawa mebli biurowych", "Dostawa energii elektrycznej na lata 2027–2028",
                "Dostawa paliw płynnych do pojazdów służbowych", "Dostawa odczynników laboratoryjnych wraz z dzierżawą analizatorów"],
    "uslugi": ["Odbiór i zagospodarowanie odpadów komunalnych z terenu Gminy {T}", "Świadczenie usług sprzątania obiektów",
               "Ochrona fizyczna osób i mienia", "Usługa utrzymania i rozwoju systemu dziedzinowego",
               "Zimowe utrzymanie dróg w sezonach 2026/2027 i 2027/2028", "Pełnienie funkcji inspektora nadzoru inwestorskiego",
               "Przygotowywanie i dostarczanie posiłków dla pacjentów", "Usługi pocztowe w obrocie krajowym i zagranicznym"],
}
NUMERY = ["ZP.271.{a}.2026", "DZP.260.{a}.2026", "ZP/PN/{a}/2026", "SZP-{a}/26", "WIM.271.1.{a}.2026",
          "NZ.DZ.{a}.2026", "ZOZ/ZP/{a}/2026", "IZP.272.{a}.2026", "AZ/{a}/2026/TP", "ZP.26.{a}.2026.MS",
          "DA.ZP.242.{a}.2026", "{a}/ZP/2026", "ZDW-DZ-{a}/26", "TI.271.{a}.2026"]

# ------------------------------------------------------------------------------------------------ challenged actions

CZYNNOSC = {
    1: ("Decyzja o odrzuceniu oferty",
        ["czynności odrzucenia oferty Odwołującego na podstawie art. 226 ust. 1 pkt 5 Pzp, o której Zamawiający poinformował {dp}",
         "odrzucenia oferty złożonej przez Odwołującego jako rzekomo niezgodnej z warunkami zamówienia (informacja Zamawiającego {dp})"]),
    2: ("Ogłoszenie wyboru oferty",
        ["wyboru jako najkorzystniejszej oferty wykonawcy {W}, o którym Zamawiający zawiadomił {dp}",
         "czynności wyboru oferty najkorzystniejszej złożonej przez {W}, ogłoszonej {dp}"]),
    3: ("Decyzja o wykluczeniu wykonawcy",
        ["wykluczenia Odwołującego z postępowania na podstawie art. 109 ust. 1 pkt 7 Pzp, o którym Zamawiający poinformował {dp}",
         "czynności wykluczenia Odwołującego z udziału w postępowaniu, zakomunikowanej pismem {dp}"]),
    4: ("Publikacja specyfikacji warunków zamówienia (SWZ)",
        ["treści Specyfikacji Warunków Zamówienia opublikowanej {dp} na stronie prowadzonego postępowania",
         "postanowień SWZ udostępnionej przez Zamawiającego {dp}, w zakresie warunków udziału w postępowaniu"]),
    5: ("Modyfikacja treści SWZ",
        ["zmiany treści SWZ dokonanej przez Zamawiającego {dp} (modyfikacja nr 2)",
         "modyfikacji Specyfikacji Warunków Zamówienia opublikowanej {dp}, którą Zamawiający zmienił kryteria oceny ofert"]),
    6: ("Odpowiedzi/wyjaśnienia do SWZ",
        ["wyjaśnień treści SWZ udzielonych przez Zamawiającego {dp} (odpowiedź na pytanie nr 14)",
         "odpowiedzi na pytania wykonawców do SWZ opublikowanych {dp}"]),
    7: ("Zaniechanie odrzucenia oferty",
        ["zaniechania odrzucenia oferty wykonawcy {W}, pomimo że jej treść jest niezgodna z warunkami zamówienia (informacja o wyniku {dp})",
         "zaniechania odrzucenia oferty {W} zawierającej rażąco niską cenę, ujawnionego w informacji Zamawiającego {dp}"]),
    8: ("Zaniechanie wykluczenia wykonawcy",
        ["zaniechania wykluczenia z postępowania wykonawcy {W}, który wprowadził Zamawiającego w błąd (informacja o wyborze {dp})",
         "zaniechania wykluczenia wykonawcy {W}, o czym Odwołujący dowiedział się z informacji Zamawiającego {dp}"]),
    9: ("Decyzja o unieważnieniu postępowania",
        ["unieważnienia postępowania na podstawie art. 255 pkt 3 Pzp, o którym Zamawiający poinformował {dp}",
         "czynności unieważnienia postępowania o udzielenie zamówienia, ogłoszonej przez Zamawiającego {dp}"]),
    10: ("Zaniechanie unieważnienia postępowania",
         ["zaniechania unieważnienia postępowania, pomimo że jest ono obarczone niemożliwą do usunięcia wadą (informacja o wyniku {dp})",
          "zaniechania unieważnienia postępowania mimo przekroczenia kwoty przeznaczonej na sfinansowanie zamówienia, ujawnionego {dp}"]),
    11: ("Opis przedmiotu zamówienia (OPZ)",
         ["opisu przedmiotu zamówienia zawartego w załączniku nr 1 do SWZ opublikowanym {dp}, który utrudnia uczciwą konkurencję",
          "sporządzenia opisu przedmiotu zamówienia (OPZ, opublikowany {dp}) w sposób wskazujący na konkretnego producenta"]),
    12: ("Projektowane postanowienia umowy",
         ["projektowanych postanowień umowy (załącznik nr 4 do SWZ, opublikowany {dp}) w zakresie kar umownych",
          "postanowień wzoru umowy udostępnionego {dp}, przewidujących nieograniczoną odpowiedzialność wykonawcy"]),
}
SECOND = ["zaniechania wezwania Odwołującego do złożenia wyjaśnień w trybie art. 223 ust. 1 Pzp",
          "dokonania oceny ofert z naruszeniem zasady równego traktowania wykonawców",
          "zaniechania udostępnienia Odwołującemu pełnej dokumentacji postępowania",
          "nieprawidłowego przyznania punktów w kryterium „doświadczenie personelu”",
          "zaniechania wezwania wykonawcy do uzupełnienia podmiotowych środków dowodowych"]
FILLER = [
    "Zgodnie z art. 16 Pzp Zamawiający przygotowuje i przeprowadza postępowanie o udzielenie zamówienia w sposób zapewniający zachowanie uczciwej konkurencji oraz równe traktowanie wykonawców, a także w sposób przejrzysty i proporcjonalny. Wbrew tej zasadzie Zamawiający dokonał czynności, która w sposób istotny ogranicza krąg wykonawców zdolnych do realizacji zamówienia.",
    "Odwołujący ma interes w uzyskaniu zamówienia, ponieważ jest wykonawcą profesjonalnie działającym na rynku objętym przedmiotem postępowania i złożył ofertę, która w prawidłowo przeprowadzonym postępowaniu zostałaby uznana za najkorzystniejszą. W wyniku naruszenia przepisów ustawy Odwołujący może ponieść szkodę polegającą na utracie spodziewanego zysku.",
    "Krajowa Izba Odwoławcza wielokrotnie wskazywała, że zamawiający nie może interpretować treści dokumentów zamówienia na niekorzyść wykonawców, jeżeli niejasność wynika z nieprecyzyjnego sformułowania tych dokumentów przez samego zamawiającego (por. wyrok KIO z dnia 12 marca 2024 r., sygn. akt KIO 611/24).",
    "Zamawiający nie wykazał, aby wskazane przez niego okoliczności miały jakikolwiek wpływ na możliwość prawidłowej realizacji zamówienia. Uzasadnienie czynności ogranicza się do ogólnikowych stwierdzeń, które nie pozwalają wykonawcy na zweryfikowanie motywów, jakimi kierował się Zamawiający.",
    "Wskazać należy, że wyjaśnienia złożone przez Odwołującego były kompletne, a załączone do nich dowody, w tym kalkulacja kosztów pracy, oferty podwykonawców oraz zestawienie zrealizowanych dostaw, potwierdzają realność zaoferowanej ceny.",
    "Nie sposób również pominąć, że wykonawca, którego ofertę wybrano, nie wykazał spełniania warunku udziału w postępowaniu dotyczącego zdolności technicznej lub zawodowej. Przedstawione referencje dotyczą zamówień o odmiennym zakresie i wartości, a ich treść nie pozwala na ustalenie, czy roboty zostały wykonane należycie.",
    "W orzecznictwie utrwalony jest pogląd, że opis przedmiotu zamówienia powinien odzwierciedlać rzeczywiste potrzeby zamawiającego, a nie preferencje dotyczące konkretnego rozwiązania technicznego. Wymagania, które nie znajdują uzasadnienia w obiektywnych potrzebach zamawiającego, stanowią nieuprawnione ograniczenie konkurencji.",
    "Odwołujący podkreśla, że kara umowna w wysokości 0,5% wynagrodzenia za każdy dzień zwłoki, bez górnego limitu, jest rażąco wygórowana i narusza zasadę proporcjonalności, o której mowa w art. 433 pkt 1 i art. 436 pkt 3 Pzp.",
    "Termin na wniesienie odwołania został zachowany. Odwołujący uiścił wpis w wymaganej wysokości na rachunek bankowy Urzędu Zamówień Publicznych, a kopię odwołania przekazał Zamawiającemu przed upływem terminu do jego wniesienia, przy użyciu środków komunikacji elektronicznej.",
    "Mając na uwadze powyższe, zaskarżona czynność Zamawiającego została dokonana z naruszeniem przepisów ustawy, co miało lub mogło mieć istotny wpływ na wynik postępowania. Odwołanie zasługuje zatem na uwzględnienie w całości.",
    "Dodatkowo Odwołujący wskazuje, że Zamawiający w toku badania ofert prowadził korespondencję wyłącznie z jednym z wykonawców, nie informując pozostałych uczestników postępowania o treści udzielanych wyjaśnień, co narusza zasadę jawności postępowania.",
    "Powyższe stanowisko znajduje potwierdzenie w wyroku Sądu Okręgowego w Warszawie – Sądu Zamówień Publicznych z dnia 8 listopada 2023 r. (sygn. akt XXIII Zs 87/23), w którym sąd wskazał, że wezwanie do wyjaśnień musi być konkretne i odnosić się do rzeczywistych wątpliwości zamawiającego.",
]
PETITUM = ["unieważnienia zaskarżonej czynności Zamawiającego", "powtórzenia czynności badania i oceny ofert",
           "nakazania Zamawiającemu dokonania zmiany treści SWZ zgodnie z żądaniami odwołania",
           "dopuszczenia i przeprowadzenia dowodów wskazanych w treści odwołania",
           "zasądzenia od Zamawiającego na rzecz Odwołującego kosztów postępowania odwoławczego, w tym kosztów zastępstwa prawnego"]


# ------------------------------------------------------------------------------------------------ case model

@dataclass
class Case:
    idx: int
    r: random.Random
    odw: list            # [Entity] leader first
    consortium: bool
    zam: list            # [Entity]
    lead_zam: int | None
    agent: Person | None
    firm: str | None     # law firm name
    agent_mail: str | None
    attorneys: list      # [Person] in the power of attorney
    wybrany: Entity
    kind: str            # roboty/dostawy/uslugi
    eu: bool
    tytul: str
    numer: str
    bzp: str | None
    ted: str | None
    reason: int
    act_date: dt.date
    filing: dt.date
    city: str
    poa_date: dt.date


def build_case(idx: int, seed: int, reason: int) -> Case:
    r = random.Random(seed * 1000 + idx)
    used, names = set(), set()
    kind_odw = r.choices(["spzoo", "sa", "spk", "spj", "jdg", "kons"], [30, 13, 12, 7, 16, 22])[0]
    consortium = kind_odw == "kons"
    if consortium:
        odw = [company(r, r.choice(["spzoo", "sa", "spk"]), used, names),
               company(r, r.choice(["spzoo", "jdg", "spj"]), used, names)]
        if r.random() < 0.3:
            odw.append(company(r, "spzoo", used, names))
    else:
        odw = [company(r, kind_odw, used, names)]
    zam = [public_entity(r, names)]
    lead_zam = None
    if r.random() < 0.18:
        zam.append(public_entity(r, names))
        lead_zam = 0
    has_agent = r.random() < 0.85
    agent = firm = mail = None
    attorneys = []
    if has_agent:
        agent = person(r, used, r.choice(["r. pr.", "r. pr.", "adw.", "adw."]))
        attorneys = [agent]
        for _ in range(r.choice([0, 0, 1, 1, 2])):
            attorneys.append(person(r, used, r.choice(["r. pr.", "adw.", "apl. radc."])))
        kind_firm = r.random()
        if kind_firm < 0.35:
            firm = f"Kancelaria {'Radcy Prawnego' if agent.title == 'r. pr.' else 'Adwokacka'} {agent.nom}"
        elif kind_firm < 0.7:
            a2 = attorneys[1] if len(attorneys) > 1 else person(r, used)
            firm = f"{agent.last[0]}, {a2.last[0]} i Wspólnicy {r.choice(['Kancelaria Prawna sp.k.', 'Kancelaria Radców Prawnych sp. p.', 'sp. k.'])}"
        elif kind_firm < 0.85:
            firm = f"Kancelaria Prawa Zamówień Publicznych {r.choice(ROOT_A)}{r.choice(['lex', 'jus', 'legal'])} sp. z o.o."
        else:
            firm = f"{r.choice(['Legalis', 'Praetor', 'Iustitia', 'Concordia', 'Verdict'])} {r.choice(['Kancelaria Adwokacka', 'Adwokaci i Radcowie Prawni', 'Legal sp.j.'])}"
        dom = _slug(firm.split()[1] if firm.startswith("Kancelaria") else firm.split()[0])
        mail = r.choice([f"{agent.first[0][0].lower()}.{_slug(agent.last[0])}@{dom}.example",
                         f"kancelaria@{dom}.example", f"{_slug(agent.last[0])}@{dom}.example"])
    kind = r.choice(list(TITLES))
    eu = r.random() < 0.5
    t = r.choice(TITLES[kind]).replace("{n}", str(r.randint(1000, 1999))).replace("{k}", str(r.randint(2, 14)))
    town = r.choice(TOWNS)
    t = t.replace("w {T}", town[1]).replace("{T}", town[0])
    numer = r.choice(NUMERY).replace("{a}", str(r.randint(3, 180)))
    bzp = ted = None
    if eu:
        ted = f"{r.randint(100000, 899999)}-2026"
        if r.random() < 0.15:
            bzp = f"2026/BZP{r.randint(100000, 799999):08d}"
    else:
        bzp = f"2026/BZP{r.randint(100000, 799999):08d}" + (f"/{r.randint(1, 3):02d}" if r.random() < 0.4 else "")
    act = dt.date(2026, r.randint(2, 10), r.randint(1, 26))
    filing = act + dt.timedelta(days=r.randint(3, 10) if reason not in (4, 11, 12) else r.randint(5, 10))
    wybrany = company(r, r.choice(["spzoo", "sa", "spk"]), used, names)
    city = (agent and r.random() < 0.6 and r.choice(TOWNS)[0]) or odw[0].town[0]
    return Case(idx, r, odw, consortium, zam, lead_zam, agent, firm, mail, attorneys, wybrany, kind, eu, t, numer,
                bzp, ted, reason, act, filing, city, filing - dt.timedelta(days=r.randint(0, 6)))


def wpis_amount(c: Case) -> float:
    if c.eu:
        return 20000.0 if c.kind == "roboty" else 15000.0
    return 10000.0 if c.kind == "roboty" else 7500.0


# ------------------------------------------------------------------------------------------------ pdf helpers

@dataclass
class Look:
    font: str
    size: float
    lead: float
    align: int
    margins: tuple
    footer: int          # 0 none, 1 "Strona x", 2 "- x -", 3 "x/N"


def make_look(r: random.Random, font: str | None = None) -> Look:
    font = font or r.choice(FONTS)
    size = r.choice([9.5, 10, 10.5, 11, 11.5, 12]) if font not in ("Verdana", "Tahoma") else r.choice([9, 9.5, 10])
    return Look(font, size, size * r.uniform(1.18, 1.45), r.choice([TA_JUSTIFY, TA_JUSTIFY, TA_LEFT]),
                tuple(r.uniform(1.6, 2.8) * cm for _ in range(4)), r.randint(0, 3))


def styles(lk: Look) -> dict:
    base = ParagraphStyle("b", fontName=lk.font, fontSize=lk.size, leading=lk.lead, alignment=lk.align, spaceAfter=lk.size * 0.45)
    return {
        "b": base,
        "l": ParagraphStyle("l", parent=base, alignment=TA_LEFT, spaceAfter=0),
        "r": ParagraphStyle("r", parent=base, alignment=TA_RIGHT, spaceAfter=0),
        "c": ParagraphStyle("c", parent=base, alignment=TA_CENTER),
        "h": ParagraphStyle("h", parent=base, alignment=TA_CENTER, fontName=lk.font + "-B", fontSize=lk.size * 1.45,
                            leading=lk.size * 1.9, spaceBefore=lk.size * 0.6, spaceAfter=lk.size * 0.7),
        "h2": ParagraphStyle("h2", parent=base, alignment=TA_LEFT, fontName=lk.font + "-B", spaceBefore=lk.size * 0.5),
        "s": ParagraphStyle("s", parent=base, fontSize=lk.size * 0.8, leading=lk.size, alignment=TA_LEFT, spaceAfter=0),
        "li": ParagraphStyle("li", parent=base, leftIndent=lk.size * 1.6, firstLineIndent=-lk.size * 1.1),
    }


def P(text: str, st, raw: bool = False) -> Paragraph:
    return Paragraph(text if raw else escape(text).replace("\n", "<br/>"), st)


def B(text: str) -> str:
    return f"<b>{escape(text)}</b>"


def lines(*xs) -> str:
    return "<br/>".join(x for x in xs if x)


def build_pdf(path: Path, story: list, lk: Look, first_page=None, later_pages=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def footer(canv, doc):
        if lk.footer:
            canv.saveState()
            canv.setFont(lk.font, 8)
            n = canv.getPageNumber()
            txt = {1: f"Strona {n}", 2: f"- {n} -", 3: f"str. {n}"}[lk.footer]
            canv.drawCentredString(A4[0] / 2, 1.0 * cm, txt)
            canv.restoreState()

    def fp(canv, doc):
        if first_page:
            first_page(canv, doc)
        footer(canv, doc)

    def lp(canv, doc):
        if later_pages:
            later_pages(canv, doc)
        footer(canv, doc)

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=lk.margins[0], rightMargin=lk.margins[1],
                            topMargin=lk.margins[2], bottomMargin=lk.margins[3], title="", author="", creator="")
    doc.build(story, onFirstPage=fp, onLaterPages=lp)


def esign_box(name: str, d: dt.date, r: random.Random, st) -> Table:
    t = Table([[P(f"Podpisany elektronicznie przez:\n{name}\nData: {d:%Y.%m.%d} {r.randint(8, 22):02d}:{r.randint(0, 59):02d}:{r.randint(0, 59):02d} +02'00'", st)]],
              colWidths=[6.3 * cm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#2a6f2a")),
                           ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef7ee"))]))
    t.hAlign = "RIGHT"
    return t


# ------------------------------------------------------------------------------------------------ appeal

def ids_text(e: Entity, r: random.Random, show: dict, nipfmt: int, sep: str) -> str:
    parts = []
    if show["krs"] and e.krs:
        parts.append(r.choice(["KRS: ", "KRS ", "nr KRS: "]) + e.krs)
    if show["nip"]:
        parts.append(r.choice(["NIP: ", "NIP ", "NIP: "]) + fmt_nip(e.nip, nipfmt))
    if show["regon"]:
        parts.append(r.choice(["REGON: ", "REGON "]) + e.regon)
    return sep.join(parts)


def appeal(c: Case, path: Path, layout: int, lk: Look) -> tuple[dict, dict]:
    r, st = c.r, styles(lk)
    lead = c.odw[0]
    show = {"krs": r.random() < 0.85, "nip": r.random() < 0.9, "regon": r.random() < 0.7}
    zshow = [{"krs": r.random() < 0.5, "nip": r.random() < 0.7, "regon": r.random() < 0.45} for _ in c.zam]
    nipfmt = r.choice([0, 0, 1, 2, 3])
    sep = r.choice([", ", " | ", "; ", "\n"])
    dstyle = r.randint(0, 5)
    header_date = f"{c.city}, {r.choice(['dnia ', ''])}{fmt_date(c.filing, dstyle)}" if r.random() < 0.85 else f"{c.city} {c.filing:%d.%m.%Y}"
    dp_style = r.randint(0, 4)
    dp = {0: f"w dniu {fmt_date(c.act_date, 1)}", 1: f"dnia {fmt_date(c.act_date, 0)}", 2: f"w dniu {fmt_date(c.act_date, 3)}",
          3: f"pismem z dnia {fmt_date(c.act_date, 2)}", 4: f"w dniu {fmt_date(c.act_date, 4)}"}[dp_style]
    act1 = r.choice(CZYNNOSC[c.reason][1]).replace("{dp}", dp).replace("{W}", c.wybrany.name)
    act2 = r.choice(SECOND)

    kio = lines("Prezes Krajowej Izby Odwoławczej", "ul. Postępu 17A", "02-676 Warszawa") if r.random() < 0.5 else \
        lines("Do", B("Prezesa Krajowej Izby Odwoławczej"), "ul. Postępu 17a, 02-676 Warszawa")
    ids = ids_text(lead, r, show, nipfmt, sep)
    sp_word = "reprezentowany" if lead.kind == "jdg" else "reprezentowana"

    # agent block, sometimes declined
    agent_txt = ""
    declined = False
    if c.agent:
        a = c.agent
        v = r.randint(0, 3)
        if v == 0:
            agent_txt = lines(f"{sp_word} przez: {a.title} {a.nom}", f"adres do korespondencji: {c.firm}, {r.choice(STREETS)} {r.randint(1, 60)}, {r.randint(0, 99):02d}-{r.randint(0, 999):03d} {r.choice(TOWNS)[0]}",
                              f"e-mail: {c.agent_mail}")
        elif v == 1:
            agent_txt = lines(f"{sp_word} przez pełnomocnika: {a.title_long()} {a.nom}", c.firm, f"{c.agent_mail}")
        elif v == 2:
            declined = True
            agent_txt = lines(f"{sp_word} przez {a.title_acc()} {a.acc}", f"({c.firm})", f"adres e-mail do doręczeń: {c.agent_mail}")
        else:
            agent_txt = lines(f"Pełnomocnik: {a.title} {a.nom}, {c.firm}", f"tel. +48 {r.randint(500, 799)} {r.randint(100, 999)} {r.randint(100, 999)}, e-mail: {c.agent_mail}")

    if c.consortium:
        members = []
        for i, m in enumerate(c.odw):
            role = "Lider konsorcjum" if i == 0 else f"Członek konsorcjum"
            mids = ids_text(m, r, show if i == 0 else {"krs": True, "nip": True, "regon": False}, nipfmt, ", ")
            members.append(lines(f"{i + 1}) {B(m.name)} ({role})", m.address, mids))
        odw_block = lines("Wykonawcy wspólnie ubiegający się o udzielenie zamówienia:", *members, agent_txt)
    else:
        jdg = f"przedsiębiorca prowadzący działalność gospodarczą pod firmą {lead.name}" if lead.kind == "jdg" and r.random() < 0.5 else ""
        odw_block = lines(B(lead.name), lead.address, ids, jdg,
                          f"e-mail: {lead.email}" if not c.agent and r.random() < 0.7 else "", agent_txt)

    zam_blocks = []
    for i, z in enumerate(c.zam):
        extra = ""
        if c.lead_zam is not None:
            extra = "(Zamawiający prowadzący postępowanie)" if i == c.lead_zam else "(Zamawiający udzielający zamówienia wspólnie)"
        zam_blocks.append(lines(B(z.name), z.address, ids_text(z, r, zshow[i], nipfmt, ", "), extra,
                                f"e-mail: {z.email}" if r.random() < 0.6 else ""))
    zam_block = "<br/>".join(zam_blocks)

    tryb = r.choice(["w trybie przetargu nieograniczonego", "w trybie podstawowym bez negocjacji",
                     "w trybie przetargu ograniczonego", "w trybie podstawowym, o którym mowa w art. 275 pkt 1 Pzp"])
    refs = []
    nr_lbl = r.choice(["nr referencyjny:", "znak sprawy:", "numer postępowania:", "nr sprawy:", "oznaczenie sprawy:"])
    refs.append(f"{nr_lbl} {c.numer}")
    if c.bzp:
        b = c.bzp
        printed = r.choice([b[:8] + " " + b[8:], b, b.replace("BZP", "BZP ")])
        refs.append(f"ogłoszenie o zamówieniu w Biuletynie Zamówień Publicznych nr {printed}")
    if c.ted:
        n, y = c.ted.split("-")
        printed = r.choice([f"{y}/S {r.randint(10, 250):03d}-{n}", c.ted, f"{n}-{y}"])
        refs.append(f"ogłoszenie w Dzienniku Urzędowym Unii Europejskiej nr {printed}")
    dot = f"postępowania o udzielenie zamówienia publicznego prowadzonego {tryb} pn. „{c.tytul}”, " + ", ".join(refs)
    wpis = f"Wpis od odwołania: {fmt_amount(wpis_amount(c), 5)}"

    story = []
    title = P("ODWOŁANIE", st["h"])
    sub = P(r.choice(["od czynności i zaniechań Zamawiającego", "wobec czynności Zamawiającego", ""]), st["c"])

    def para_dotyczy():
        return P(f"{B('Dotyczy:')} {escape(dot)}", st["b"], raw=True)

    if layout == 0:      # classic stacked, UZP template
        story += [P(header_date, st["r"]), Spacer(1, 10), P(kio, st["l"], raw=True), Spacer(1, 12),
                  P(B("Odwołujący:"), st["l"], raw=True), P(odw_block, st["l"], raw=True), Spacer(1, 8),
                  P(B("Zamawiający:"), st["l"], raw=True), P(zam_block, st["l"], raw=True), Spacer(1, 8),
                  para_dotyczy(), P(wpis, st["l"]), title, sub]
    elif layout == 1:    # two-column label table (as on many real appeals)
        rows = [[P(B("Odwołujący:"), st["l"], raw=True), P(odw_block, st["l"], raw=True)],
                [P(B("Zamawiający:"), st["l"], raw=True), P(zam_block, st["l"], raw=True)],
                [P(B("Dotyczy:"), st["l"], raw=True), P(escape(dot), st["l"], raw=True)]]
        t = Table(rows, colWidths=[3.3 * cm, None])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        story += [P(header_date, st["r"]), Spacer(1, 6), P(kio, st["r"], raw=True), Spacer(1, 12), t,
                  P(B(wpis), st["l"], raw=True), title, sub]
    elif layout == 2:    # KIO first, date below, Odwołujący before Zamawiający, separate pełnomocnik label
        story += [P(kio, st["l"], raw=True), Spacer(1, 6), P(header_date, st["r"]), Spacer(1, 10),
                  P(f"{B('Odwołujący:')} {odw_block}", st["l"], raw=True), Spacer(1, 8),
                  P(f"{B('Zamawiający:')} {zam_block}", st["l"], raw=True), Spacer(1, 8),
                  title, sub, para_dotyczy()]
    elif layout == 3:    # law-firm letterhead, prose parties
        story += [P(header_date, st["r"]), Spacer(1, 16), P(kio, st["r"], raw=True), Spacer(1, 14), title,
                  P(f"{B('Odwołujący:')} {odw_block}", st["l"], raw=True), Spacer(1, 6),
                  P(f"{B('Zamawiający:')} {zam_block}", st["l"], raw=True), Spacer(1, 6), para_dotyczy(),
                  P(f"Wartość zamówienia: {'równa lub przekraczająca progi unijne' if c.eu else 'mniejsza niż progi unijne'}. {wpis}.", st["b"])]
    elif layout == 4:    # typewriter look, uppercase labels, dashed separators
        story += [P(header_date, st["l"]), Spacer(1, 6), P(kio.upper(), st["r"], raw=True), P("-" * 60, st["l"]),
                  P("ODWOŁUJĄCY:", st["h2"]), P(odw_block, st["l"], raw=True), P("ZAMAWIAJĄCY:", st["h2"]),
                  P(zam_block, st["l"], raw=True), P("-" * 60, st["l"]), para_dotyczy(), title]
    else:                # dotyczy first, then parties in a boxed table, date at top-left
        rows = [[P(B("ODWOŁUJĄCY"), st["c"], raw=True), P(B("ZAMAWIAJĄCY"), st["c"], raw=True)],
                [P(odw_block, st["l"], raw=True), P(zam_block, st["l"], raw=True)]]
        t = Table(rows, colWidths=[None, None])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8"))]))
        story += [P(header_date, st["l"]), Spacer(1, 4), P(kio, st["r"], raw=True), Spacer(1, 8), para_dotyczy(),
                  Spacer(1, 6), t, Spacer(1, 4), P(wpis, st["r"]), title]

    who = c.agent.title + " " + c.agent.nom if c.agent else "Zarząd"
    lead_in = r.choice([
        f"Działając w imieniu Odwołującego, na podstawie pełnomocnictwa załączonego do odwołania, na podstawie art. 505 ust. 1 w zw. z art. 513 pkt 1 i 2 ustawy z dnia 11 września 2019 r. – Prawo zamówień publicznych (t.j. Dz. U. z 2024 r. poz. 1320 ze zm., dalej: „Pzp”), wnoszę odwołanie wobec:",
        f"Na podstawie art. 513 pkt 1 Pzp, w imieniu {lead.name} (dalej: „Odwołujący”), wnoszę odwołanie od niezgodnych z przepisami ustawy czynności i zaniechań Zamawiającego, polegających na:",
        f"W imieniu Odwołującego wnoszę odwołanie od:",
    ])
    story += [P(lead_in, st["b"]), P(f"1) {act1};", st["li"]), P(f"2) {act2}.", st["li"])]
    story += [P(r.choice(["Zaskarżonym czynnościom zarzucam naruszenie:", "Odwołujący zarzuca Zamawiającemu naruszenie:"]), st["b"]),
              P("1) art. 16 pkt 1 i 2 Pzp w zw. z art. 226 ust. 1 Pzp poprzez dokonanie czynności opisanej w pkt 1 powyżej;", st["li"]),
              P("2) art. 239 ust. 1 Pzp poprzez " + act2 + ".", st["li"]),
              P("Wnoszę o:", st["b"])]
    for i, p in enumerate(r.sample(PETITUM, 3)):
        story.append(P(f"{i + 1}) {p};", st["li"]))
    story.append(P(r.choice(["UZASADNIENIE", "Uzasadnienie", "I. Stan faktyczny"]), st["h2"]))
    distract = r.choice([
        f"Zamawiający wszczął postępowanie ogłoszeniem z dnia {fmt_date(c.act_date - dt.timedelta(days=r.randint(30, 70)), 1)}. Termin składania ofert upłynął {fmt_date(c.act_date - dt.timedelta(days=r.randint(8, 25)), 0)}.",
        f"Oferty w postępowaniu złożyło {r.randint(2, 7)} wykonawców, w tym {c.wybrany.name} z siedzibą {c.wybrany.town[1]} (KRS {c.wybrany.krs}, NIP {c.wybrany.nip}).",
    ])
    story.append(P(distract, st["b"]))
    for ptxt in r.sample(FILLER, r.randint(4, 9)):
        story.append(P(ptxt, st["b"]))
    story.append(P("Załączniki:", st["h2"]))
    for i, z in enumerate(r.sample(["dowód uiszczenia wpisu od odwołania", "pełnomocnictwo wraz z dowodem uiszczenia opłaty skarbowej",
                                    "dowód przekazania kopii odwołania Zamawiającemu", "odpis z KRS Odwołującego",
                                    "informacja o wyborze najkorzystniejszej oferty"], 3)):
        story.append(P(f"{i + 1}. {z}", st["l"]))
    story.append(Spacer(1, 18))
    if r.random() < 0.35:
        story.append(esign_box(c.agent.nom if c.agent else lead.signers[0][0].nom, c.filing, r, st["s"]))
    else:
        signer = f"{c.agent.title} {c.agent.nom}" if c.agent else f"{lead.signers[0][0].nom} – {lead.signers[0][1]}"
        story += [P("…………………………………", st["r"]), P(signer, st["r"])]

    first_page = None
    if layout == 3 and c.firm:
        def first_page(canv, doc, firm=c.firm, mail=c.agent_mail, font=lk.font):
            canv.saveState()
            canv.setFont(font + "-B", 11)
            canv.drawString(lk.margins[0], A4[1] - 1.2 * cm, firm)
            canv.setFont(font, 8)
            canv.drawString(lk.margins[0], A4[1] - 1.65 * cm, f"{mail} · tel. 22 000 00 00")
            canv.setStrokeColor(colors.HexColor("#7a1f1f"))
            canv.line(lk.margins[0], A4[1] - 1.85 * cm, A4[0] - lk.margins[1], A4[1] - 1.85 * cm)
            canv.restoreState()
        lk.margins = (lk.margins[0], lk.margins[1], max(lk.margins[2], 2.6 * cm), lk.margins[3])
    build_pdf(path, story, lk, first_page)

    gold = {
        "OdwolanieKIO": {"data": c.filing.isoformat(), "czynnosc_dzien": c.act_date.isoformat(), "czynnosc_powod_id": c.reason,
                         "czynnosc_opis": CZYNNOSC[c.reason][0], "miejscowosc": c.city},
        "Odwolujacy": [{
            "krs": lead.krs if show["krs"] and lead.krs else None, "nazwa": lead.name,
            "nip": lead.nip if show["nip"] else None, "regon": lead.regon if show["regon"] else None,
            "przez-pelnomocnika": 1 if c.agent else 0,
            "pelnomocnik": {"imie_nazwisko": c.agent.nom if c.agent else None, "nazwa": c.firm if c.agent else None,
                            "mail": c.agent_mail if c.agent else None}}],
        "Zamawiajacy": [{"krs": z.krs if zshow[i]["krs"] and z.krs else None, "nazwa": z.name,
                         "nip": z.nip if zshow[i]["nip"] else None, "regon": z.regon if zshow[i]["regon"] else None,
                         "prowadzacy_postepowanie": (None if c.lead_zam is None else (1 if i == c.lead_zam else 0))}
                        for i, z in enumerate(c.zam)],
        "ZamowieniePubliczne": {"numer_bzp": c.bzp, "numer_postepowania": c.numer, "numer_ted": c.ted, "tytul": c.tytul},
    }
    return gold, {"declined_agent": declined, "date_style": dstyle, "nip_style": nipfmt}


# ------------------------------------------------------------------------------------------------ power of attorney

def poa(c: Case, path: Path, layout: int, lk: Look, members: list, attorneys: list) -> tuple[dict, dict]:
    r, st = c.r, styles(lk)
    show_krs, show_nip = r.random() < 0.8, r.random() < 0.85
    use_alt = r.random() < 0.4
    nipfmt = r.choice([0, 0, 1, 2])
    place = f"{r.choice([c.odw[0].town[0], c.city])}, {r.choice(['dnia ', ''])}{fmt_date(c.poa_date, r.randint(0, 5))}"
    proc = f"„{c.tytul}” (nr {c.numer})" if r.random() < 0.7 else f"„{c.tytul}”"
    zam = c.zam[c.lead_zam or 0].name
    pesel_on = r.random() < 0.45
    lead = members[0]

    def mname(m):
        return m.alt_name if use_alt else m.name

    def mdesc(m):
        if m.kind == "jdg":
            return f"{m.owner.nom}, prowadzący działalność gospodarczą pod firmą {m.name}, {m.address}" + \
                   (f", NIP {fmt_nip(m.nip, nipfmt)}" if show_nip else "")
        s = f"{mname(m)} z siedzibą {m.town[1]}, {m.address}"
        if show_krs and m.krs:
            s += r.choice([f", wpisana do rejestru przedsiębiorców KRS pod numerem {m.krs}", f", KRS {m.krs}", f", nr KRS: {m.krs}"])
        if show_nip:
            s += f", NIP {fmt_nip(m.nip, nipfmt)}"
        return s

    def att_desc(a, case="nom"):
        nm = {"nom": a.nom, "dat": a.dat, "acc": a.acc}[case]
        ttl = a.title_long() or ""
        s = f"{ttl} {nm}".strip() if case == "nom" else nm
        if pesel_on:
            s += f", PESEL {a.pesel}"
        elif a.title in ("r. pr.", "adw.") and r.random() < 0.5:
            s += f" (nr wpisu {r.choice(['WA', 'KR', 'PO', 'GD', 'WR'])}-{r.randint(1000, 9999)})"
        return s

    story = []
    title = P(r.choice(["PEŁNOMOCNICTWO", "P E Ł N O M O C N I C T W O", "Pełnomocnictwo procesowe"]), st["h"])
    declined = False
    if layout == 0:      # paragraphs § (UZP style)
        story += [title, P(place, st["c"]), P("§ 1. Mocodawca", st["h2"])]
        story += [P(f"Mocodawcą jest {mdesc(m)}." if len(members) == 1 else f"{i + 1}) {mdesc(m)};", st["b"]) for i, m in enumerate(members)]
        story += [P("§ 2. Pełnomocnik", st["h2"])]
        story += [P(f"{i + 1}. {att_desc(a)}", st["li"]) for i, a in enumerate(attorneys)]
        story += [P("§ 3. Zakres", st["h2"]),
                  P(f"Pełnomocnik jest umocowany do reprezentowania Mocodawcy przed Krajową Izbą Odwoławczą w sprawie odwołania dotyczącego postępowania {proc}, prowadzonego przez {zam}, w tym do wniesienia odwołania, udziału w posiedzeniach i rozprawach oraz cofnięcia odwołania.", st["b"])]
    elif layout == 1:    # short prose, KIO template for a company, dative
        declined = True
        who = " oraz ".join(mdesc(m) for m in members)
        atts = ", ".join(f"{'Pani' if a.female else 'Panu'} {att_desc(a, 'dat')}" for a in attorneys)
        story += [P(place, st["r"]), Spacer(1, 10), title,
                  P(f"Działając w imieniu {who}, niniejszym {'udzielamy' if len(members) > 1 or len(lead.signers) > 1 else 'udzielam'} pełnomocnictwa {atts} do reprezentowania Mocodawcy przed Krajową Izbą Odwoławczą w sprawie dotyczącej postępowania o udzielenie zamówienia publicznego pn. {proc} prowadzonego przez {zam}, w szczególności do:", st["b"])]
        for x in ["wniesienia odwołania do Krajowej Izby Odwoławczej,", "reprezentowania na posiedzeniu i rozprawie,",
                  "wnoszenia pism procesowych,", "cofnięcia odwołania."]:
            story.append(P("- " + x, st["li"]))
        story.append(P("Pełnomocnik jest uprawniony do udzielania dalszych pełnomocnictw w granicach określonych niniejszym pełnomocnictwem.", st["b"]))
    elif layout == 2:    # table form
        rows = [[P(B("Mocodawca"), st["l"], raw=True), P("<br/>".join(escape(mdesc(m)) for m in members), st["l"], raw=True)],
                [P(B("Pełnomocnik / Pełnomocnicy"), st["l"], raw=True), P("<br/>".join(escape(att_desc(a)) for a in attorneys), st["l"], raw=True)],
                [P(B("Postępowanie"), st["l"], raw=True), P(f"{proc}, Zamawiający: {zam}", st["l"])],
                [P(B("Zakres umocowania"), st["l"], raw=True), P("reprezentowanie przed Krajową Izbą Odwoławczą, wniesienie i cofnięcie odwołania, zawarcie ugody, udzielanie dalszych pełnomocnictw", st["l"])]]
        t = Table(rows, colWidths=[4.2 * cm, None])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f0f0"))]))
        story += [P(place, st["r"]), title, t, Spacer(1, 8)]
    elif layout == 3:    # individual entrepreneur "Ja, niżej podpisany"
        declined = True
        own = lead.owner if lead.kind == "jdg" else lead.signers[0][0]
        story += [P(place, st["r"]), Spacer(1, 8), title]
        if lead.kind == "jdg":
            txt = f"Ja, niżej {'podpisana' if own.female else 'podpisany'} {own.nom}, {'prowadząca' if own.female else 'prowadzący'} działalność gospodarczą pod firmą {lead.name}, {lead.address}" + \
                  (f", NIP {fmt_nip(lead.nip, nipfmt)}" if show_nip else "") + ", "
        else:
            txt = f"Ja, niżej {'podpisana' if own.female else 'podpisany'} {own.nom}, działając jako {lead.signers[0][1]} w imieniu {mdesc(lead)}, "
        atts = " oraz ".join(f"{a.title_acc()} {a.acc}" + (f" (PESEL {a.pesel})" if pesel_on else "") for a in attorneys)
        story.append(P(txt + f"upoważniam {atts} do reprezentowania mnie przed Krajową Izbą Odwoławczą w postępowaniu odwoławczym dotyczącym zamówienia {proc}, w tym do podpisania i wniesienia odwołania.", st["b"]))
    else:                # consortium "My, niżej podpisani"
        story += [title, P(place, st["c"]),
                  P("My, niżej podpisani, działając w imieniu wykonawców wspólnie ubiegających się o udzielenie zamówienia:", st["b"])]
        story += [P(f"{i + 1}) {mdesc(m)} – {'Lider' if i == 0 else 'Partner'},", st["li"]) for i, m in enumerate(members)]
        story.append(P(f"ustanawiamy pełnomocnikiem {'' if len(attorneys) == 1 else 'każdego z osobna'}:", st["b"]))
        story += [P(f"– {att_desc(a)}", st["li"]) for a in attorneys]
        story.append(P(f"do reprezentowania wykonawców przed Krajową Izbą Odwoławczą w sprawie odwołania w postępowaniu {proc} prowadzonym przez {zam}.", st["b"]))

    story.append(Spacer(1, 22))
    sig_rows = []
    for m in members:
        for pers, func in m.signers:
            sig_rows.append([P("……………………………", st["l"]), ""])
            sig_rows.append([P(f"{pers.nom}" + (f" – {func}" if r.random() < 0.7 else ""), st["s"]),
                             P(f"za: {mname(m)}" if len(members) > 1 else "", st["s"])])
    t = Table(sig_rows, colWidths=[7 * cm, None])
    t.hAlign = "RIGHT" if r.random() < 0.5 else "LEFT"
    story.append(KeepTogether([P(r.choice(["Podpisy osób uprawnionych do reprezentacji Mocodawcy:", "Za Mocodawcę:", "Mocodawca:"]), st["l"]), t]))
    if r.random() < 0.3:
        story += [Spacer(1, 10), P(f"Opłatę skarbową w wysokości 17 zł uiszczono w dniu {fmt_date(c.poa_date, 2)}.", st["s"])]
    build_pdf(path, story, lk)

    gold = {"mocodawca": [], "pelnomocnicy": [{"imie_nazwisko": a.nom, "pesel": a.pesel if pesel_on else None} for a in attorneys]}
    for m in members:
        if m.kind == "jdg":
            data = {"imie_nazwisko": m.owner.nom, "krs": None, "nazwa": m.name, "nip": m.nip if show_nip else None, "typ": "osoba_fizyczna"}
        else:
            data = {"imie_nazwisko": None, "krs": m.krs if show_krs else None, "nazwa": mname(m),
                    "nip": m.nip if show_nip else None, "typ": "osoba_prawna"}
        gold["mocodawca"].append({"data": data, "podpisujacy": [{"imie_nazwisko": p.nom} for p, _ in m.signers]})
    return gold, {"declined_attorney": declined, "pesel": pesel_on}


# ------------------------------------------------------------------------------------------------ bank transfer

BANKS = [("Bank Nadwiślański S.A.", "1160", "#0b4f8a"), ("Pomorski Bank Spółdzielczy", "8350", "#2e7d32"),
         ("Mazowiecki Bank Handlowy S.A.", "1050", "#e65100"), ("Bank Hanzeatycki Polska S.A.", "1240", "#b71c1c"),
         ("Alpejski Bank Polska S.A.", "2490", "#4a148c"), ("Bank Rolniczo-Kredytowy", "9070", "#33691e"),
         ("Śląski Bank Komercyjny S.A.", "1050", "#263238"), ("Bank Kujawski", "1020", "#01579b")]


@dataclass
class Transfer:
    payer: str
    payer_addr: str
    payee: str
    payee_addr: str
    z: str
    na: str
    amount: float
    op_date: dt.date
    title: str
    txn: str | None


def transfers_for(c: Case) -> list[Transfer]:
    r = c.r
    lead = c.odw[0]
    pay_by_firm = c.agent is not None and r.random() < 0.25
    payer = c.firm if pay_by_firm else lead.name
    payer_addr = f"{r.choice(STREETS)} {r.randint(1, 50)}, {r.choice(TOWNS)[0]}" if pay_by_firm else lead.address
    acct = nrb(r)
    zam_short = c.zam[0].name.upper()[:40]
    titles = [f"Wpis od odwołania {c.numer}", f"WPIS OD ODWOŁANIA, ZAM: {zam_short}, {c.numer}",
              f"wpis od odwołania - postępowanie nr {c.numer}", f"Odwołanie KIO – {c.tytul[:45].rstrip(' —–-')} – {c.numer}",
              f"WPIS ODW. {lead.name.upper()[:30]} / {c.numer}"]
    pay_day = c.filing - dt.timedelta(days=r.randint(0, 2))
    txn = r.choice([None, f"{r.choice(['CEN', 'TRN', 'EL', 'PB'])}{pay_day:%y%m%d}{r.randint(10 ** 9, 10 ** 10 - 1)}",
                    f"{r.randint(10 ** 14, 10 ** 15 - 1)}", f"OP/{pay_day:%Y/%m}/{r.randint(10000, 99999)}"])
    out = [Transfer(payer, payer_addr, "Urząd Zamówień Publicznych", "ul. Postępu 17A, 02-676 Warszawa", acct, UZP_ACCOUNT,
                    wpis_amount(c), pay_day, r.choice(titles), txn)]
    if c.agent and r.random() < 0.6:
        town = r.choice(TOWNS)
        names = " i ".join(a.nom for a in c.attorneys[:2])
        t2 = r.choice([f"opłata skarbowa od pełnomocnictwa dla {names}", f"Opłata skarbowa - pełnomocnictwo KIO {c.numer}",
                       f"OPŁATA SKARBOWA ZA PEŁNOMOCNICTWO {c.agent.nom.upper()}"])
        d2 = c.poa_date + dt.timedelta(days=r.randint(0, 1))
        txn2 = r.choice([None, f"{r.choice(['CEN', 'TRN'])}{d2:%y%m%d}{r.randint(10 ** 9, 10 ** 10 - 1)}"])
        out.append(Transfer(payer, payer_addr, f"Urząd Miasta {town[0]}", f"{r.choice(STREETS)} {r.randint(1, 30)}, {town[0]}",
                            acct, nrb(r), 17.0, d2, t2, txn2))
    return out


def transfer_pdf(c: Case, tr: Transfer, path: Path, layout: int, lk: Look, scanned: bool) -> tuple[dict, dict]:
    r, st = c.r, styles(lk)
    bank, _, color = r.choice(BANKS)
    col = colors.HexColor(color)
    zst, nst = r.choice([0, 1, 1, 2, 3]), r.choice([0, 1, 1, 2, 3])
    ast, dst = r.choice([0, 0, 1, 2, 4]), r.randint(0, 3)
    z, na = fmt_acct(tr.z, zst), fmt_acct(tr.na, nst)
    amt, dd = fmt_amount(tr.amount, ast), fmt_bank_date(tr.op_date, dst)
    printed = tr.op_date + dt.timedelta(days=r.randint(0, 3))
    lab = lambda s: P(B(s), st["l"], raw=True)
    val = lambda s: P(escape(s), st["l"], raw=True)
    story = []
    op_label = r.choice(["Data operacji", "Data wykonania", "Data realizacji", "Data transakcji"])
    if layout == 0:      # key: value list
        story += [P(B(bank), st["l"], raw=True), P(f"Wydrukowano: {fmt_bank_date(printed, dst)}", st["r"]),
                  P(r.choice(["Potwierdzenie wykonania przelewu", "Potwierdzenie realizacji polecenia przelewu"]), st["h"])]
        rows = [("Zleceniodawca", f"{tr.payer}\n{tr.payer_addr}"), ("Z rachunku", z), ("Odbiorca", f"{tr.payee}\n{tr.payee_addr}"),
                ("Na rachunek", na), ("Kwota", amt), (op_label, dd), ("Tytuł", tr.title)]
        if tr.txn:
            rows.append((r.choice(["Numer referencyjny", "Nr transakcji", "Identyfikator operacji"]), tr.txn))
        rows += [("Typ operacji", r.choice(["Przelew krajowy ELIXIR", "Przelew natychmiastowy", "Przelew SORBNET"])), ("Status", "Zrealizowany")]
        t = Table([[lab(k), val(v)] for k, v in rows], colWidths=[4.5 * cm, None])
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#bbbbbb")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
    elif layout == 1:    # coloured band + two-column sender/receiver
        band = Table([[P(f"<font color='white'><b>{escape(bank)}</b></font>", st["l"], raw=True),
                       P(f"<font color='white'>{fmt_bank_date(printed, dst)}</font>", st["r"], raw=True)]], colWidths=[None, 5 * cm])
        band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), col), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
        story += [band, P("Potwierdzenie operacji", st["h"])]
        t = Table([[lab("Nadawca"), lab("Odbiorca")], [val(f"{tr.payer}\n{tr.payer_addr}\n{z}"), val(f"{tr.payee}\n{tr.payee_addr}\n{na}")]],
                  colWidths=[None, None])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), 0.8, col)]))
        story += [t, Spacer(1, 10)]
        rows = [("Kwota przelewu", amt), (op_label, dd), ("Tytułem", tr.title)] + ([("Nr ref.", tr.txn)] if tr.txn else []) + \
               [("Opłata", "0,00 PLN"), ("Kanał", r.choice(["Bankowość internetowa", "Aplikacja mobilna", "Serwis transakcyjny"]))]
        t2 = Table([[lab(k), val(v)] for k, v in rows], colWidths=[4 * cm, None])
        story.append(t2)
    elif layout == 2:    # statement row (Data | Opis | Kwota)
        story += [P(f"<font color='{color}' size='{lk.size * 1.6}'><b>{escape(bank)}</b></font>", st["l"], raw=True), Spacer(1, 8),
                  P(f"Data wydruku: {fmt_bank_date(printed, dst)} godz. {r.randint(8, 21):02d}:{r.randint(0, 59):02d}", st["l"]), Spacer(1, 10)]
        desc = lines(B("PRZELEW ELIXIR - ONLINE"), f"{B('Z rachunku:')} {escape(z)}", escape(f"{tr.payer} {tr.payer_addr}").upper(),
                     f"{B('Na rachunek:')} {escape(na)}", escape(tr.payee), f"Tytuł: {escape(tr.title)}",
                     f"Nr transakcji: {escape(tr.txn)}" if tr.txn else "")
        t = Table([[lab("Data"), lab("Opis"), lab("Kwota")],
                   [P(f"{op_label}<br/>{dd}<br/>Data księgowania<br/>{dd}", st["s"], raw=True), P(desc, st["s"], raw=True),
                    P(fmt_amount(tr.amount, 4), st["r"])]], colWidths=[3.2 * cm, None, 3 * cm])
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
    elif layout == 3:    # big amount on top, mobile-app style
        story += [P(f"<font color='{color}'><b>{escape(bank)}</b></font>", st["c"], raw=True),
                  P("Potwierdzenie transakcji", st["c"]),
                  P(f"<font size='{lk.size * 2.2}'><b>{escape(fmt_amount(tr.amount, 0))}</b></font>", st["c"], raw=True), Spacer(1, 16)]
        rows = [("Odbiorca", tr.payee), ("Rachunek odbiorcy", na), ("Tytuł", tr.title), ("Nadawca", tr.payer), ("Rachunek nadawcy", z),
                (op_label, dd)] + ([("ID transakcji", tr.txn)] if tr.txn else [])
        for k, v in rows:
            story += [P(f"<font color='#777777'>{escape(k)}</font>", st["l"], raw=True), P(escape(v), st["l"]), Spacer(1, 4)]
    elif layout == 4:    # bilingual corporate
        story += [P(B(f"{bank} – Corporate Banking"), st["l"], raw=True),
                  P("Potwierdzenie przelewu / Transfer confirmation", st["h"])]
        rows = [("Rachunek obciążany / Debit account", z), ("Zleceniodawca / Ordering party", tr.payer),
                ("Rachunek uznawany / Credit account", na), ("Beneficjent / Beneficiary", f"{tr.payee}, {tr.payee_addr}"),
                ("Kwota / Amount", amt), (f"{op_label} / Value date", dd), ("Tytuł / Details", tr.title)] + \
               ([("Referencja / Reference", tr.txn)] if tr.txn else [])
        t = Table([[P(escape(k), st["s"]), val(v)] for k, v in rows], colWidths=[6 * cm, None])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f4f4f4")),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story.append(t)
    else:                # paper form (polecenie przelewu) with digit boxes
        story += [P(B(f"POLECENIE PRZELEWU / WPŁATA GOTÓWKOWA – {bank}"), st["l"], raw=True), Spacer(1, 6)]

        def boxes(s):
            cells = [[P(ch, st["c"]) for ch in s.replace(" ", "")]]
            t = Table(cells, colWidths=[0.55 * cm] * len(cells[0]), rowHeights=[0.6 * cm])
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c0392b")), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
            return t
        story += [P("nazwa odbiorcy", st["s"]), P(tr.payee, st["l"]), P("nr rachunku odbiorcy", st["s"]), boxes(tr.na),
                  P("kwota", st["s"]), P(fmt_amount(tr.amount, 3), st["l"]), P("nr rachunku zleceniodawcy", st["s"]), boxes(tr.z),
                  P("nazwa zleceniodawcy", st["s"]), P(f"{tr.payer}, {tr.payer_addr}", st["l"]), P("tytułem", st["s"]), P(tr.title, st["l"]),
                  Spacer(1, 10), P(f"{op_label}: {dd}" + (f"     Nr operacji: {tr.txn}" if tr.txn else ""), st["l"]),
                  P("stempel banku / podpis", st["s"])]
        z, na, zst, nst = tr.z, tr.na, 2, 2
    story += [Spacer(1, 24), P(r.choice(["Dokument wygenerowany elektronicznie, nie wymaga podpisu ani stempla.",
                                         "Bank nie ponosi odpowiedzialności za treść tytułu przelewu podaną przez klienta.",
                                         f"{bank}, KRS {krs(r)}, kapitał zakładowy opłacony w całości."]), st["s"])]
    build_pdf(path, story, lk)
    gold = {"przelew_bankowy": {"data_operacji": tr.op_date.isoformat(), "kwota": tr.amount,
                                "na_rachunek": acct_gold(tr.na, nst, scanned), "numer_transakcji": tr.txn,
                                "tytul": tr.title, "z_rachunku": acct_gold(tr.z, zst, scanned)}}
    return gold, {"bank": bank}


# ------------------------------------------------------------------------------------------------ negatives

def negative_pdf(c: Case, path: Path, kind: int, lk: Look) -> dict:
    r, st = c.r, styles(lk)
    lead, zam = c.odw[0], c.zam[0]
    story = []
    if kind == 0:        # e-mail printout: proof of sending a copy to the contracting authority
        story += [P(B(f"Od: {c.agent_mail or lead.email}"), st["l"], raw=True), P(f"Do: {zam.email}", st["l"]),
                  P(f"Wysłano: {fmt_date(c.filing, 0)} {r.randint(9, 15)}:{r.randint(10, 59)}", st["l"]),
                  P(f"Temat: Kopia odwołania – {c.numer}", st["l"]), P("Załączniki: odwolanie.pdf; pelnomocnictwo.pdf; wpis.pdf", st["l"]),
                  Spacer(1, 10), P(f"Szanowni Państwo, w załączeniu przekazuję kopię odwołania wniesionego w dniu dzisiejszym do Prezesa Krajowej Izby Odwoławczej w postępowaniu „{c.tytul}”.", st["b"]),
                  P("Z poważaniem", st["l"])]
        what = "email_copy"
    elif kind == 1:      # KRS extract
        story += [P("CENTRALNA INFORMACJA KRAJOWEGO REJESTRU SĄDOWEGO", st["c"]),
                  P(f"Stan na dzień {fmt_date(c.filing - dt.timedelta(days=2), 2)}", st["c"]),
                  P("Informacja odpowiadająca odpisowi aktualnemu z rejestru przedsiębiorców", st["h"])]
        rows = [("Numer KRS", lead.krs or krs(r)), ("Firma, pod którą spółka działa", lead.name.upper()), ("NIP", lead.nip),
                ("REGON", lead.regon), ("Siedziba", lead.town[0]), ("Adres", lead.address)]
        t = Table([[P(k, st["s"]), P(v, st["l"])] for k, v in rows], colWidths=[6 * cm, None])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey)]))
        story += [t, Spacer(1, 8), P("Dział 2 – Rubryka 1 – Organ uprawniony do reprezentacji podmiotu: ZARZĄD", st["b"])]
        story += [P(f"{p.last[0].upper()} {p.first[0].upper()} – {f.upper()}", st["l"]) for p, f in lead.signers]
        what = "krs"
    elif kind == 2:      # notice of the best offer from the contracting authority
        story += [P(f"{zam.town[0]}, {fmt_date(c.act_date, 1)}", st["r"]), P(B(zam.name), st["l"], raw=True), P(f"Znak: {c.numer}", st["l"]),
                  P("INFORMACJA O WYBORZE NAJKORZYSTNIEJSZEJ OFERTY", st["h"]),
                  P(f"Zamawiający informuje, że w postępowaniu pn. „{c.tytul}” jako najkorzystniejszą wybrano ofertę złożoną przez {c.wybrany.name}, {c.wybrany.address}. Oferta uzyskała 100,00 pkt.", st["b"])]
        t = Table([["Nr oferty", "Wykonawca", "Punkty"], ["1", c.wybrany.name, "100,00"], ["2", lead.name, f"{r.uniform(80, 99):.2f}".replace('.', ',')]],
                  colWidths=[2 * cm, None, 2.5 * cm])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.black), ("FONTNAME", (0, 0), (-1, -1), lk.font)]))
        story.append(t)
        what = "wybor"
    else:                # invoice for legal services
        story += [P(B(c.firm or lead.name), st["l"], raw=True), P(f"FAKTURA VAT nr {r.randint(1, 300)}/{c.filing:%m/%Y}", st["h"]),
                  P(f"Data wystawienia: {fmt_bank_date(c.filing, 1)}", st["l"]), P(f"Nabywca: {lead.name}, NIP {lead.nip}", st["l"])]
        net = r.choice([3600, 5000, 7200])
        t = Table([["Lp.", "Nazwa usługi", "Netto", "VAT", "Brutto"],
                   ["1", f"Sporządzenie odwołania do KIO ({c.numer})", f"{net},00", "23%", f"{net * 1.23:.2f}".replace('.', ',')]],
                  colWidths=[1 * cm, None, 2.3 * cm, 1.5 * cm, 2.5 * cm])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.black), ("FONTNAME", (0, 0), (-1, -1), lk.font), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
        story += [t, Spacer(1, 6), P(f"Do zapłaty na rachunek {fmt_acct(nrb(r), 1)} w terminie 14 dni.", st["l"])]
        what = "invoice"
    build_pdf(path, story, lk)
    return {"negative": what}


# ------------------------------------------------------------------------------------------------ scanning

def _page_images(pdf: Path, dpi: int) -> list[Image.Image]:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        return [doc[i].render(scale=dpi / 72.0).to_pil().convert("RGB") for i in range(len(doc))]
    finally:
        doc.close()


def _font(size: int):
    try:
        return ImageFont.truetype(str(fonts_dir() / "cour.ttf"), size)
    except OSError:
        return ImageFont.load_default()


def scan_fax(img: Image.Image, rng: np.random.Generator, page: int, n: int, stamp: str) -> Image.Image:
    g = img.convert("L")
    w, h = g.size
    g = g.resize((w, h // 2), Image.BILINEAR).resize((w, h), Image.NEAREST)          # 98 lpi vertical
    g = g.rotate(float(rng.uniform(-0.8, 0.8)), resample=Image.BICUBIC, fillcolor=255)
    a = np.asarray(g, dtype=np.float32)
    a = np.where(a < rng.uniform(150, 185), 0, 255).astype(np.float32)
    for _ in range(int(rng.integers(2, 7))):                                             # drop-out / streak lines
        y = int(rng.integers(0, h - 3))
        a[y:y + int(rng.integers(1, 3)), :] = 255 if rng.random() < 0.6 else a[y:y + 1, :] * 0
    mask = rng.random(a.shape) < 0.0015
    a[mask] = 0
    out = Image.fromarray(a.astype(np.uint8))
    d = ImageDraw.Draw(out)
    d.text((int(w * 0.04), 8), f"{stamp}   S. {page + 1:02d}/{n:02d}", fill=0, font=_font(max(14, w // 70)))
    return out


def scan_copy(img: Image.Image, rng: np.random.Generator) -> Image.Image:
    g = img.convert("L")
    w, h = g.size
    g = g.rotate(float(rng.uniform(-2.2, 2.2)), resample=Image.BICUBIC, fillcolor=255)
    a = np.asarray(g, dtype=np.float32)
    a = 40 + a * rng.uniform(0.70, 0.82)                                                  # grey paper, faded toner
    xx = np.linspace(-1, 1, w)[None, :]
    a = a - 60 * np.clip(np.abs(xx) - 0.88, 0, None) / 0.12                                # dark edges
    a += rng.normal(0, 6, a.shape)
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))
    if rng.random() < 0.6:                                                                 # punch holes
        d = ImageDraw.Draw(out)
        r_ = w // 45
        for y in (h * 0.35, h * 0.65):
            d.ellipse([w * 0.03, y - r_, w * 0.03 + 2 * r_, y + r_], fill=25)
    return out


def scan_phone(img: Image.Image, rng: np.random.Generator) -> Image.Image:
    w, h = img.size
    pad = int(w * 0.04)
    canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad), (95, 80, 60))                    # desk behind the sheet
    canvas.paste(img, (pad, pad))
    W, H = canvas.size
    j = lambda: float(rng.uniform(0, 0.025)) * W
    quad = (j(), j(), j(), H - j(), W - j(), H - j(), W - j(), j())
    canvas = canvas.transform((W, H), Image.QUAD, quad, resample=Image.BICUBIC)
    a = np.asarray(canvas, dtype=np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vign = 1 - 0.35 * (((xx / W - 0.5) ** 2 + (yy / H - 0.5) ** 2) / 0.5)
    shadow = 1 - 0.18 * np.clip((xx / W - rng.uniform(0.5, 0.9)) * 4, 0, 1)
    a = a * (vign * shadow)[..., None] * np.array([1.0, 0.97, 0.9])                        # warm light
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(float(rng.uniform(0.6, 1.2))))
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=int(rng.integers(55, 75)))
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def scan_pdf(src: Path, dst: Path, mode: str, seed: int, stamp: str) -> None:
    rng = np.random.default_rng(seed)
    dpi = {"office": 200, "fax": 200, "copy": 180, "phone": 150}[mode]
    pages = _page_images(src, dpi)
    out = []
    for i, p in enumerate(pages):
        if mode == "office":
            out.append(make_noisy.degrade_image(p, rng))
        elif mode == "fax":
            out.append(scan_fax(p, rng, i, len(pages), stamp))
        elif mode == "copy":
            out.append(scan_copy(p, rng))
        else:
            out.append(scan_phone(p, rng))
    out[0].save(dst, format="PDF", save_all=True, append_images=out[1:], resolution=float(dpi))


# ------------------------------------------------------------------------------------------------ driver

NAME_POOL = ["zalacznik_{n}.pdf", "skan_{d}_{t}.pdf", "dokument ({n}).pdf", "IMG_{k}.pdf", "doc{k}.pdf", "plik_{n}.pdf",
             "Scan{d}.pdf", "zal{n}_KIO.pdf", "{d}_pismo.pdf", "SKM_C{k}.pdf", "akta_{n}.pdf", "wydruk_{k}.pdf"]


def file_name(r: random.Random, used: set, d: dt.date) -> str:
    while True:
        n = r.choice(NAME_POOL).format(n=r.randint(1, 9), d=f"{d:%Y%m%d}", t=f"{r.randint(800, 1800):04d}", k=r.randint(1000, 9999))
        if n not in used:
            used.add(n)
            return n


def generate(out: Path, n_cases: int, seed: int, scan_share: float) -> dict:
    register_fonts()
    if out.exists():
        shutil.rmtree(out)
    tmp = out / "_born_digital"
    reasons = [(i % 12) + 1 for i in range(n_cases)]
    random.Random(seed).shuffle(reasons)
    rr = random.Random(seed + 7)
    odw_layouts = [i % 6 for i in range(n_cases)]
    rr.shuffle(odw_layouts)
    poa_layouts = [i % 5 for i in range(n_cases * 2)]
    rr.shuffle(poa_layouts)
    tr_layouts = [i % 6 for i in range(n_cases * 2)]
    rr.shuffle(tr_layouts)
    scan_modes = ["office", "fax", "copy", "phone"]
    manifest = {"seed": seed, "cases": {}}
    pi = ti = 0
    neg_kind = 0
    for i in range(1, n_cases + 1):
        c = build_case(i, seed, reasons[i - 1])
        r = c.r
        name = f"synth_{i:02d}"
        used: set = set()
        docs = []

        def place(kind, writer, layout, meta_extra=None):
            nonlocal docs
            fname = file_name(r, used, c.filing)
            scanned = r.random() < scan_share
            mode = r.choice(scan_modes) if scanned else None
            lk = make_look(r, "CourierNew" if (kind == "odwolanie" and layout == 4 and "CourierNew" in FONTS) else None)
            born = tmp / name / fname
            gold, meta = writer(born, layout, lk, scanned)
            dst = out / "input" / name / fname
            dst.parent.mkdir(parents=True, exist_ok=True)
            if scanned:
                stamp = f"{c.filing:%d/%m/%Y} {r.randint(8, 17):02d}:{r.randint(0, 59):02d}  FAX +48 {r.randint(12, 95)} {r.randint(100, 999)} {r.randint(10, 99)} {r.randint(10, 99)}"
                scan_pdf(born, dst, mode, seed * 7919 + i * 101 + len(docs), stamp)
            else:
                shutil.copy2(born, dst)
            if gold is not None:
                g = out / "gold" / name / (Path(fname).stem + ".json")
                g.parent.mkdir(parents=True, exist_ok=True)
                g.write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
            docs.append({"file": fname, "class": kind, "layout": layout, "font": lk.font, "scan": mode, **(meta or {}), **(meta_extra or {})})

        place("odwolanie", lambda p, lay, lk, sc: appeal(c, p, lay, lk), odw_layouts[i - 1])
        if c.agent:
            if c.consortium and r.random() < 0.4:      # each consortium member signs its own power of attorney
                for m in c.odw:
                    lay = poa_layouts[pi % len(poa_layouts)]
                    pi += 1
                    lay = 3 if (m.kind == "jdg" and lay == 4) else (0 if lay == 4 else lay)
                    place("pelnomocnictwo", lambda p, lay_, lk, sc, m=m: poa(c, p, lay_, lk, [m], c.attorneys), lay)
            else:
                lay = poa_layouts[pi % len(poa_layouts)]
                pi += 1
                if c.consortium:
                    lay = r.choice([4, 4, 0, 2])
                elif lay == 4:
                    lay = 3 if c.odw[0].kind == "jdg" else r.choice([0, 1, 2])
                elif lay == 3 and c.odw[0].kind != "jdg" and r.random() < 0.5:
                    lay = 1
                place("pelnomocnictwo", lambda p, lay_, lk, sc: poa(c, p, lay_, lk, c.odw, c.attorneys), lay)
        for tr in transfers_for(c):
            lay = tr_layouts[ti % len(tr_layouts)]
            ti += 1
            place("przelew", lambda p, lay_, lk, sc, tr=tr: transfer_pdf(c, tr, p, lay_, lk, sc), lay)
        if r.random() < 0.4:
            k = neg_kind % 4
            neg_kind += 1
            place("negatywny", lambda p, lay_, lk, sc, k=k: (None, negative_pdf(c, p, k, lk)), k)
        manifest["cases"][name] = {"reason": c.reason, "consortium": c.consortium, "odw_kind": c.odw[0].kind,
                                   "agent": bool(c.agent), "zamawiajacy": len(c.zam), "eu": c.eu, "docs": docs}
    shutil.rmtree(tmp, ignore_errors=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--cases", type=int, default=20)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--scan-share", type=float, default=0.35)
    a = ap.parse_args(argv)
    m = generate(a.out, a.cases, a.seed, a.scan_share)
    docs = [d for c in m["cases"].values() for d in c["docs"]]
    by = {}
    for d in docs:
        by[d["class"]] = by.get(d["class"], 0) + 1
    print(f"make_synth: {len(m['cases'])} cases, {len(docs)} documents {by}, scanned {sum(1 for d in docs if d['scan'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
