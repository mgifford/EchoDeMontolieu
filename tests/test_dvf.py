import sqlite3

from echo_montolieu import dvf

HEAD = "id_mutation,date_mutation,nature_mutation,valeur_fonciere,adresse_numero,adresse_suffixe,adresse_nom_voie,code_commune,id_parcelle,type_local,surface_reelle_bati,nombre_pieces_principales,surface_terrain\n"
ROWS = [
    "2024-1,2024-12-05,Vente,150000,5,,RUE SAINT DENIS,11253,11253000AB0546,Maison,80,4,\n",
    "2024-1,2024-12-05,Vente,150000,5,,RUE SAINT DENIS,11253,11253000AB0546,,,,120\n",             # same sale, a land line
    "2025-2,2025-03-01,Vente,40000,,,VIGNOBLE DE SAINT DENIS,11253,112530000A0345,,,,4825\n",
    "2025-3,2025-04-01,Echange,0,2,,RUE DES ÉCOLES,11253,112530000B0010,Appartement,50,2,\n",
    "2025-4,2025-05-01,Vente,99000,1,,RUE AILLEURS,11999,11999000AB0001,Maison,60,3,\n",             # another commune: ignored
]


def folder(tmp_path):
    (tmp_path / "dvf").mkdir()
    (tmp_path / "dvf/dvf-2025.csv").write_text(HEAD + "".join(ROWS), encoding="utf-8")
    return tmp_path / "dvf"


def test_a_sale_is_one_mutation_with_its_price_surfaces_and_parcels_counted_once(tmp_path):
    sales = {s["id"]: s for s in dvf.load(folder(tmp_path))}
    assert set(sales) == {"2024-1", "2025-2", "2025-3"}
    s = sales["2024-1"]
    assert s["price"] == 150000 and s["built"] == 80 and s["land"] == 120 and s["parcels"] == {("AB", "0546")} and s["types"] == {"Maison"}
    assert sales["2025-2"]["parcels"] == {("A", "0345")}                      # a one-letter section is stored as 0A in the cadastre


def test_search_ignores_accents_and_case_and_leaves_out_exchanges(tmp_path):
    sales = dvf.load(folder(tmp_path))
    assert [s["id"] for s in dvf.search(sales, street="saint denis")] == ["2025-2", "2024-1"]
    assert dvf.search(sales, street="ecoles") == [] and [s["id"] for s in dvf.search(sales, street="ecoles", nature=None)] == ["2025-3"]
    assert [s["id"] for s in dvf.search(sales, section="ab")] == ["2024-1"]


def test_council_notices_are_paired_with_the_recorded_sale_of_the_same_parcel(tmp_path):
    db_path = tmp_path / "private.db"
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE meetings (id TEXT, date TEXT)")
    db.execute("CREATE TABLE parcels (meeting_id TEXT, page INTEGER, section TEXT, number TEXT, form TEXT, ocr INTEGER, context TEXT)")
    db.execute("INSERT INTO meetings VALUES ('m1', '2024-10-23')")
    db.executemany("INSERT INTO parcels VALUES ('m1', 7, ?, ?, 'table', 0, '')", [("AB", "0546"), ("AB", "0999")])
    db.commit()
    db.close()
    pairs = dvf.match_notices(dvf.load(folder(tmp_path)), db_path)
    assert [(p["notice"], p["parcel"], p["sale"]["price"]) for p in pairs] == [("2024-10-23", "AB 0546", 150000.0)]
    assert "RUE SAINT DENIS" in dvf.describe(pairs[0]["sale"])
