"""Query Azure's public Retail Prices API for the Data Zone Standard 5.6 sol/luna meters
seen on the Aug 8 invoice. Run: python worklogs/assets/2026-11-09-azure-retail-prices-probe.py
Finding (run 2026-11-09): sol rows all effective 2026-09-01 (4.4/0.44/22 in westus) -- AFTER
the Aug 8 runs; luna rows in westus effective 2026-08-01 (0.22/0.022/1.32) -- IN FORCE on Aug 8.
The API does not list pre-Sept-1 sol prices."""
import urllib.request, urllib.parse, json
def q(flt):
    url = "https://prices.azure.com/api/retail/prices?api-version=2023-01-01-preview&" + urllib.parse.urlencode({"$filter": flt})
    out = []
    while url:
        d = json.load(urllib.request.urlopen(url)); out += d["Items"]; url = d.get("NextPageLink")
    return out
for m in ["5.6 sol ShortCo Inp Std DZ", "5.6 sol ShortCo Cd Inp Std DZ", "5.6 sol ShortCo Opt Std DZ",
          "5.6 luna ShortCo Inp Std DZ", "5.6 luna ShortCo Cd Inp Std DZ", "5.6 luna ShortCo Opt Std DZ"]:
    items = q(f"meterName eq '{m} 1M Tokens'")
    print(m, sorted({(i["retailPrice"], i["effectiveStartDate"][:10]) for i in items}),
          "westus:", [(i["retailPrice"], i["effectiveStartDate"][:10]) for i in items if i["armRegionName"] == "westus"])
