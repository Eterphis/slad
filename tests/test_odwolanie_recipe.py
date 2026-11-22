"""Shipped odwolanie recipe on a synthetic appeal written as prose (real appeals rarely have "Odwołujący:" blocks)."""
import unittest

from odw2json.engine import RecipeEngine
from odw2json.model import Document, Page

PROSE = """Warszawa, dnia 12 marca 2026 r.
Do Prezesa Krajowej Izby Odwoławczej
ODWOŁANIE
Działając w imieniu Alfa Bud sp. z o.o. z siedzibą w Warszawie, ul. Polna 1, 00-001 Warszawa, wpisanej do KRS pod nr 0000123456, NIP 1234567890, REGON 123456785 (dalej: „Odwołujący”), reprezentowanej przez adw. Jan Nowak, Kancelaria Nowak, e-mail: jan.nowak@kancelaria.pl, wnoszę odwołanie od czynności Zamawiającego z dnia 2 marca 2026 r. polegającej na wyborze oferty najkorzystniejszej.
Gmina Brzozowo, ul. Długa 5, 00-002 Brzozowo, NIP 9876543210 (dalej: „Zamawiający”).
Wykonawca wybrany Beta S.A. z siedzibą w Krakowie (KRS 0000999999) przystąpił po stronie Zamawiającego.
Odwołujący (biuro@alfabud.pl) zarzuca Zamawiającemu naruszenie art. 226 ust. 1 pkt 5 ustawy z dnia 11 września 2019 r.
"""

LABELLED = """Kraków, 03.02.2026
Odwołujący:
Gamma Serwis S.A.
ul. Krótka 2, 30-001 Kraków
KRS nr 0000555555, NIP 5260001246 00-950 Warszawa
e-mail: biuro@gamma.pl
reprezentowany przez: r. pr. Anna Lis, Kancelaria Lis, a.lis@kancelaria-lis.pl
Zamawiający:
Szpital Miejski w Krakowie
NIP 1112223344
ODWOŁANIE
Zamawiający w dniu 20.01.2026 r. odrzucił ofertę Odwołującego.
Zarzuty
"""


def extract(text):
    d = Document("o.pdf", [Page(1, 600, 800, [], text, "text")])
    eng = RecipeEngine("recipes")
    assert eng.classify(d).doc_class == "odwolanie"
    return eng.extract(d, "odwolanie").data


class OdwolanieRecipeTests(unittest.TestCase):
    def test_prose_party_intros(self):
        x = extract(PROSE)
        o, z, k = x["Odwolujacy"][0], x["Zamawiajacy"][0], x["OdwolanieKIO"]
        self.assertEqual((o["nazwa"], o["krs"], o["nip"], o["regon"]),
                         ("Alfa Bud sp. z o.o.", "0000123456", "1234567890", "123456785"))
        self.assertEqual(o["pelnomocnik"]["imie_nazwisko"], "Jan Nowak")
        self.assertEqual(o["pelnomocnik"]["mail"], "jan.nowak@kancelaria.pl")  # not the appellant's own address
        self.assertEqual(o["przez-pelnomocnika"], 1)
        self.assertEqual((z["nazwa"], z["nip"]), ("Gmina Brzozowo", "9876543210"))  # not the distractor party
        self.assertEqual((k["czynnosc_dzien"], k["czynnosc_powod_id"]), ("2026-03-02", 2))

    def test_labelled_blocks_krs_nr_nip_boundary_attorney_mail(self):
        x = extract(LABELLED)
        o = x["Odwolujacy"][0]
        self.assertEqual((o["nazwa"], o["krs"], o["nip"]), ("Gamma Serwis S.A.", "0000555555", "5260001246"))
        self.assertEqual(o["pelnomocnik"]["mail"], "a.lis@kancelaria-lis.pl")
        self.assertEqual(x["Zamawiajacy"][0]["nazwa"], "Szpital Miejski w Krakowie")
        self.assertEqual((x["OdwolanieKIO"]["czynnosc_dzien"], x["OdwolanieKIO"]["czynnosc_powod_id"]), ("2026-01-20", 1))


if __name__ == "__main__":
    unittest.main()
