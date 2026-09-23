"""core/bom_gap.py — SATU logika "model mana yang BOM-nya belum lengkap".

Dipakai papan kelengkapan R&D (`GET /api/dewi/rnd/completeness`) DAN berkas FOKUS
(`core/gap_fokus.py`), supaya angka di layar dan isi Excel tidak pernah berbeda.
"""
from __future__ import annotations

from core.bom_fill import _is_kept_line, load_model_variants


def _key(d: dict) -> tuple:
    return (d.get("size_id"), (d.get("color_code") or "").upper())


async def load_bom_state(db) -> dict:
    """→ {model_id: {"boms": [bom aktif], "keys": set, "has_acc": bool}} untuk semua BOM aktif."""
    out: dict = {}
    async for b in db.rahaza_boms.find({"active": {"$ne": False}, "is_active": True},
                                       {"_id": 0, "id": 1, "model_id": 1, "size_id": 1, "color_code": 1, "materials": 1}):
        st = out.setdefault(b["model_id"], {"boms": [], "keys": set(), "has_acc": False})
        st["boms"].append(b)
        st["keys"].add(_key(b))
        if any(not _is_kept_line(ln) for ln in b.get("materials") or []):
            st["has_acc"] = True
    return out


async def bom_gap_models(db) -> list[dict]:
    """Model aktif yang BOM-nya belum lengkap, urut kode. Setiap baris:
    code, name, category, model_id, variants (aktif), variants_without_bom, has_bom, has_acc,
    discontinued (punya varian tapi SEMUA nonaktif), status (kalimat), sheet (di mana diisi)."""
    models = await db.rahaza_models.find({"active": {"$ne": False}},
                                         {"_id": 0, "id": 1, "code": 1, "name": 1, "category_name": 1}).sort("code", 1).to_list(5000)
    vmap = await load_model_variants(db, [m["id"] for m in models])
    all_counts = {d["_id"]: d["n"] for d in await db.rahaza_model_variants.aggregate(
        [{"$group": {"_id": "$model_id", "n": {"$sum": 1}}}]).to_list(10000)}
    state = await load_bom_state(db)
    rows = []
    for m in models:
        vs = vmap.get(m["id"]) or []
        st = state.get(m["id"]) or {"boms": [], "keys": set(), "has_acc": False}
        without = [v for v in vs if _key(v) not in st["keys"]]
        discontinued = not vs and all_counts.get(m["id"], 0) > 0
        row = {"code": m["code"], "name": m["name"], "category": m.get("category_name") or "", "model_id": m["id"],
               "variants": vs, "variants_without_bom": without, "has_bom": bool(st["boms"]), "has_acc": st["has_acc"],
               "discontinued": discontinued, "boms": st["boms"]}
        if discontinued:
            row["status"], row["sheet"] = "semua SKU nonaktif (sudah tidak dijual) — tidak perlu BOM", "— (aktifkan SKU dulu bila masih dijual)"
        elif not vs:
            row["status"], row["sheet"] = "belum punya varian/SKU sama sekali", "VARIAN_BARU (warna+ukuran) lalu BOM_AKSESORIS"
        elif not st["boms"]:
            row["status"], row["sheet"] = f"belum punya BOM sama sekali ({len(vs)} varian)", "BOM_AKSESORIS (aksesoris) + R&D → BOM (kain)"
        elif without:
            row["status"], row["sheet"] = f"{len(without)} dari {len(vs)} varian belum punya BOM", "BOM_AKSESORIS (baris biru disalin dari varian lain — periksa)"
        elif not st["has_acc"]:
            row["status"], row["sheet"] = "BOM ada, aksesoris belum diisi", "BOM_AKSESORIS"
        else:
            continue
        rows.append(row)
    return rows
