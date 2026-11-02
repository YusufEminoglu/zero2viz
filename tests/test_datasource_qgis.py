# -*- coding: utf-8 -*-
"""QGIS test: external CSV columns get real types, and dates / booleans leave
the data source as chartable values (v0.20 set, items B and F).

Run from the plugins root with ``QGIS_CUSTOM_CONFIG_PATH`` set to a temp dir:
``python-qgis-ltr.bat -m zero2viz.tests.test_datasource_qgis`` (and
``python-qgis.bat``)."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import QgsApplication, QgsFeature, QgsProject, QgsVectorLayer  # noqa: E402
from qgis.PyQt.QtCore import QDate, QDateTime, QTime  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS " if condition else "FAIL ") + name + (f" — {detail}" if detail else ""),
          flush=True)
    if not condition:
        FAILURES.append(name)


def run() -> None:
    from zero2viz.core import datasource, transform

    tmp = tempfile.mkdtemp(prefix="o2viz ds şehir ")
    try:
        # 1. comma CSV with integers, decimals, dates and text
        path = os.path.join(tmp, "bütçe 2024.csv")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("district,budget,share,opened,note\n")
            for i, name in enumerate(("Konak", "Bornova", "Karşıyaka", "Buca")):
                fh.write(f"{name},{1000 + i * 250},{0.05 + i * 0.01:.2f},2024-0{i + 1}-15,ok\n")
        layer = datasource.load_table(path)
        check("csv loads", layer is not None and layer.isValid())
        check("csv uses the delimited-text provider",
              layer is not None and layer.providerType() == "delimitedtext",
              layer.providerType() if layer else "")
        types = {f.name(): f.typeName().lower() for f in layer.fields()} if layer else {}
        fields = layer.fields() if layer else None
        check("csv integer column is numeric",
              fields is not None and fields.field("budget").isNumeric(), str(types))
        check("csv decimal column is numeric",
              fields is not None and fields.field("share").isNumeric(), str(types))
        check("csv text column stays text",
              fields is not None and not fields.field("district").isNumeric(), str(types))
        cols, fids, _info = datasource.columns_with_ids_info(
            layer, ["district", "budget", "share", "opened"])
        check("csv rows", len(fids) == 4, str(len(fids)))
        check("csv numbers arrive as numbers",
              cols["budget"][:2] == [1000, 1250] and abs(cols["share"][3] - 0.08) < 1e-9,
              f"{cols['budget']} {cols['share']}")
        check("csv dates arrive as ISO text",
              cols["opened"][0] == "2024-01-15" and all(isinstance(v, str) for v in cols["opened"]),
              str(cols["opened"]))
        check("csv Turkish text intact", cols["district"][2] == "Karşıyaka", cols["district"][2])

        # 2. semicolon CSV with decimal commas (common in Turkish/European exports)
        path2 = os.path.join(tmp, "nüfus.csv")
        with open(path2, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("ilce;nufus;oran\nKonak;336545;12,5\nBuca;517963;19,25\n")
        layer2 = datasource.load_table(path2)
        cols2, _f, _i = datasource.columns_with_ids_info(layer2, ["ilce", "nufus", "oran"])
        check("semicolon csv typed", layer2.fields().field("oran").isNumeric()
              and cols2["oran"] == [12.5, 19.25] and cols2["nufus"][1] == 517963,
              f"{cols2}")

        # 3. memory layer: QDate / QDateTime / QTime / bool / NULL
        mem = QgsVectorLayer("None?field=d:date&field=dt:datetime&field=t:time&field=b:boolean"
                             "&field=s:string", "types", "memory")
        rows = [[QDate(2024, 10, 1), QDateTime(QDate(2024, 10, 1), QTime(9, 0)),
                 QTime(9, 30), True, "a"],
                [QDate(2024, 2, 1), QDateTime(QDate(2024, 2, 1), QTime(8, 0)),
                 QTime(8, 0), False, "a"],
                [None, None, None, None, None],
                [QDate(2024, 1, 1), QDateTime(QDate(2024, 1, 1), QTime(10, 0)),
                 QTime(10, 0), True, "b"]]
        feats = []
        for r in rows:
            f = QgsFeature(mem.fields())
            f.setAttributes(r)
            feats.append(f)
        mem.dataProvider().addFeatures(feats)
        QgsProject.instance().addMapLayer(mem)
        cols3, fids3, _ = datasource.columns_with_ids_info(mem, ["d", "dt", "t", "b", "s"])
        check("dates are ISO text", cols3["d"] == ["2024-10-01", "2024-02-01", None, "2024-01-01"],
              str(cols3["d"]))
        check("datetimes are ISO text", cols3["dt"][0] == "2024-10-01T09:00:00", str(cols3["dt"]))
        check("times are ISO text", cols3["t"][0] == "09:30:00", str(cols3["t"]))
        check("booleans stay booleans", cols3["b"][:2] == [True, False] and cols3["b"][2] is None,
              str(cols3["b"]))
        cats, _vals, _ids = transform.group_rows(cols3["d"], [], fids3, "count")
        check("date bars sort as dates", cats == ["2024-01-01", "2024-02-01", "2024-10-01", "(null)"],
              str(cats))
        cats, sums, _ = transform.group_rows(cols3["s"], cols3["b"], fids3, "sum")
        check("boolean sum counts true rows", list(sums) == [1.0, 0.0, 1.0], f"{cats} {list(sums)}")
    finally:
        QgsProject.instance().removeAllMapLayers()
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    app = QgsApplication([], False)
    app.initQgis()
    try:
        run()
    except Exception:
        traceback.print_exc()
        FAILURES.append("exception")
    total = "OK" if not FAILURES else f"FAILED ({len(FAILURES)}): {', '.join(FAILURES)}"
    print(f"test_datasource_qgis: {total}", flush=True)
    code = 1 if FAILURES else 0
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
    return code


if __name__ == "__main__":
    main()
