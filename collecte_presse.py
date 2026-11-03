#!/usr/bin/env python3
"""Collecte générale d'articles de presse « inondation / crue » (Google Actualités RSS),
rattachés aux communes du SPC LACI d'après leur titre.

  python collecte_presse.py --jours 30        (ou --mois 6, --annees 1)
  python collecte_presse.py --debut 2026-02-01 --fin 2026-02-28

Lit data/communes_spclaci.geojson. Écrit data/articles.csv (fusionné avec l'existant)
et data/meta.json. Optionnel : ignorer.txt (noms de communes à ne pas détecter, un par ligne).
Aucune dépendance (Python 3.9+)."""
import argparse, csv, json, re, time, unicodedata, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

PARIS, D = ZoneInfo("Europe/Paris"), Path("data")
MOTS, CAP = "inondation OR inondations OR crue OR crues", 95  # Google plafonne à ~100 résultats/requête
CHAMPS = ["date", "media", "titre", "lien", "insee", "communes", "ambigu"]

def fold(s):  # minuscules sans accents, tirets/apostrophes -> espace (1 caractère -> 1 caractère)
    out = []
    for c in s:
        b = unicodedata.normalize("NFD", c)[0]
        out.append(" " if b in "-'’" or b.isspace() else b.lower())
    return "".join(out)

def charger_communes():
    idx, f_ign = {}, Path("ignorer.txt")
    ign = {fold(l.strip()) for l in f_ign.read_text("utf-8").splitlines()} if f_ign.exists() else set()
    for f in json.load(open(D / "communes_spclaci.geojson", encoding="utf-8"))["features"]:
        p = f["properties"]; k = fold(p["NOM"])
        if k not in ign:
            idx.setdefault(k, []).append((p["INSEE_COM"], p["NOM"]))
    motif = "|".join(re.escape(k) for k in sorted(idx, key=len, reverse=True))
    return idx, re.compile(r"(?<!\w)(?:" + motif + r")(?!\w)")

def rattacher(titre, idx, motif):
    maj, ids, noms, amb = titre.isupper(), [], [], 0
    for m in motif.finditer(fold(titre)):
        if not maj and not titre[m.start()].isupper():
            continue  # exige la majuscule (évite les noms communs)
        c = idx[m.group(0)]; amb |= len(c) > 1
        for i, n in c:
            if i not in ids:
                ids.append(i); noms.append(n)
    return ids, noms, int(amb)

def telecharger(d1, d2):
    q = f"({MOTS}) after:{d1 - timedelta(1)} before:{d2 + timedelta(2)}"  # bornes élargies, filtrées ensuite
    url = f"https://news.google.com/rss/search?q={quote(q)}&hl=fr&gl=FR&ceid=FR:fr"
    for essai in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                xml = r.read()
            break
        except Exception as e:
            print(f"  essai {essai + 1} échoué ({e})"); time.sleep(5 * (essai + 1))
    else:
        return []
    time.sleep(1)
    out = []
    for it in ET.fromstring(xml).iter("item"):
        titre, media = (it.findtext("title") or "").strip(), (it.findtext("source") or "").strip()
        if media and titre.endswith(" - " + media):
            titre = titre[:-len(media) - 3]
        if not it.findtext("pubDate"):
            continue
        dt = parsedate_to_datetime(it.findtext("pubDate")).astimezone(PARIS)
        out.append({"date": dt.strftime("%Y-%m-%d %H:%M"), "media": media, "titre": titre,
                    "lien": (it.findtext("link") or "").strip()})
    return out

def collecter(d1, d2):  # si le plafond est atteint, on coupe la fenêtre en deux
    brut = telecharger(d1, d2)
    if len(brut) >= CAP:
        if d1 < d2:
            m = d1 + (d2 - d1) // 2
            return collecter(d1, m) + collecter(m + timedelta(1), d2)
        print(f"  ⚠ {d1} : plafond atteint, des articles peuvent manquer")
    return [a for a in brut if d1.isoformat() <= a["date"][:10] <= d2.isoformat()]

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--jours", type=int); p.add_argument("--mois", type=int); p.add_argument("--annees", type=int)
    p.add_argument("--debut", type=date.fromisoformat); p.add_argument("--fin", type=date.fromisoformat)
    a = p.parse_args()
    fin = a.fin or date.today()
    n = (a.jours or 0) + 30 * (a.mois or 0) + 365 * (a.annees or 0) or 30
    debut = a.debut or fin - timedelta(days=n)
    idx, motif = charger_communes()
    nouveaux, ecartes, d = {}, 0, debut
    while d <= fin:
        f = min(d + timedelta(6), fin)
        print(f"{d} → {f}")
        for art in collecter(d, f):
            ids, noms, amb = rattacher(art["titre"], idx, motif)
            if not ids:
                ecartes += 1; continue
            nouveaux[art["lien"]] = {**art, "insee": "|".join(ids), "communes": "|".join(noms), "ambigu": amb}
        d = f + timedelta(1)
    fic, meta_f = D / "articles.csv", D / "meta.json"
    tous = {}
    if fic.exists():
        tous = {r["lien"]: r for r in csv.DictReader(open(fic, encoding="utf-8", newline=""))}
    tous.update(nouveaux)
    lignes = sorted(tous.values(), key=lambda r: r["date"], reverse=True)
    with open(fic, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CHAMPS); w.writeheader(); w.writerows(lignes)
    ancien = json.load(open(meta_f, encoding="utf-8")) if meta_f.exists() else {}
    meta = {"maj": datetime.now(PARIS).isoformat(timespec="minutes"),
            "debut": min(debut.isoformat(), ancien.get("debut", "9999")),
            "fin": max(fin.isoformat(), ancien.get("fin", "0000")),
            "nb_articles": len(lignes), "ecartes_sans_commune": ecartes}
    json.dump(meta, open(meta_f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(nouveaux)} article(s) rattaché(s), {ecartes} écarté(s) sans commune. Total : {len(lignes)}")

if __name__ == "__main__":
    main()