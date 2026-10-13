# Thermal material data for the built-in materials (H2)

Status: research, 13 October 2026. Work item H2 of 0.4.2 (`docs/PLAN.md` section 4B).
Nothing in `anneal/*.py` is changed by this file. The code owner adds the values from section 4.

## 1. How the data was collected — read this first

- The search used a web search tool. The search tool returns the found pages and text excerpts
  from them.
- **The pages themselves could not be opened from this environment.** The network policy of the
  session blocks the hosts (`asm.matweb.com`, `www.matweb.com`, `www.eos.info` and others gave
  "CONNECT tunnel failed, 403"; the page-fetch tool gave "ENOTFOUND").
- So each "quote" below is the text excerpt that the search tool returned for that URL. It is
  not a copy that a person read on the page.
- **Rule for the code owner:** before a value goes into `MATERIALS`, open the URL, find the
  quoted row, and confirm the number and the unit. If the page differs, use the page value and
  correct this file. Column "Opened" says "no" for every row for this reason.
- No number in this file is an estimate. Where no source was found, the key is in section 5
  ("Gaps") and has no value.

Units: `alpha` and `alphaZ` in 1/K, `maxServiceTempC` in °C. 1 µm/(m·°C) = 1 ppm/K = 1e-6 1/K.

### 1.1 Which CTE range to use

Datasheets give a mean (secant) CTE from about 20–25 °C up to a stated upper temperature. Anneal
uses a reference temperature of 20 °C and case temperatures of about −20 to +100 °C. This file
therefore takes the **lowest range** that a source gives (for example 25–100 °C). The higher
ranges are listed in the tables for the record.

## 2. Service limit for polymers — which quantity, and the recommendation

The polymer datasheets give different quantities. They are not the same:

| Quantity | Test | What it means |
|---|---|---|
| HDT at 1.8 MPa (HDT/A) | ISO 75-2 method A, ASTM D648 at 1.82 MPa | Temperature at which a bar under 1.8 MPa bending stress deflects a set amount (0.25 mm, ASTM) while heated at 2 °C/min. Short-term. |
| HDT at 0.45 MPa (HDT/B) | ISO 75-2 method B, ASTM D648 at 0.455 MPa | The same test with a lower stress. Higher than HDT/A, much higher for semi-crystalline polymers. |
| Vicat softening (A/50: 10 N; B/50: 50 N) | ISO 306, ASTM D1525 | Temperature at which a 1 mm² needle goes 1 mm into the material. A softening point, not a stiffness limit. |
| Glass transition Tg | DSC (ISO 11357), DMA | The amorphous phase changes from glassy to rubbery. For amorphous polymers (PLA as printed, PETG) the modulus falls by a large factor in a narrow band at Tg. |
| Continuous use (RTI) | UL 746B | Long-term ageing limit. Not found for any of these materials. |

**Recommendation for Anneal: `maxServiceTempC` = HDT at 1.8 MPa (HDT/A) if the source gives it;
else HDT at 0.45 MPa (HDT/B), and only for an amorphous polymer, where HDT/B is at or below Tg.
Never use Vicat or the melting point.**

Reasons:
1. Anneal is a linear-elastic stiffness and strength check of a loaded part. HDT is a measure of
   *stiffness loss under load*, which is the failure that Anneal cannot model above the limit.
   Vicat is a surface-softening point and is always higher (PA12: 163–181 °C, near the melt).
2. For amorphous polymers (PLA, PETG) HDT/A, HDT/B and Tg are within about 15 °C of each other
   (PETG resin: 64 / 70 / 80 °C; PLA: HDT/B 58.8 °C, Tg 59.1 °C). Any of them stops the run in
   the right place; HDT is the lowest and is the one printed on filament datasheets.
3. For semi-crystalline PA12, HDT/B (about 170 °C) is near the melt and far above the
   temperature where the modulus has already fallen. HDT/A (86 °C) is the only number in the list
   that is useful as a stop.
4. HDT is a short-term value. A part that is loaded for hours at a temperature near HDT creeps.
   The report must say "service limit = HDT (short-term); creep is not modelled". Store the name
   of the quantity in the `source` text, as `docs/guides/THERMAL-IMPLEMENTATION.md` step 1 asks.
5. Without a `tempDerating` table (none was found for the polymers, section 5), Anneal uses the
   room-temperature E up to `maxServiceTempC`. The modulus already falls below HDT. The check row
   should say so when a polymer case is above about 40 °C and no table exists.

For metals, the service limit is not a stiffness-loss point. It is a supplier statement (creep,
oxidation, loss of temper). Only one sourced value was found (Ti-6Al-4V, wrought).

## 3. Tables per material

Columns: key, value (SI), source URL, document, quoted text (from the search excerpt), condition
match, opened (see section 1).

### 3.1 Ti64-LPBF

| Key | Value | URL | Document | Quote | Condition match | Opened |
|---|---|---|---|---|---|---|
| alpha | 9.0e-6 1/K | https://www.eos.info/var/assets/03_system-related-assets/material-related-contents/metal-materials-and-examples/metal-material-datasheet/titan/ti64/material_datasheet_eos_titanium_ti64_grade5_en_web.pdf (also https://www.eos.info/metal-solutions/data-sheets/titanium/pds-eos-titanium-ti64-grade5-eos-m-290-40um) | EOS, "EOS Titanium Ti64 Grade 5 Material Data Sheet", thermal properties, CTE per ASTM E228 | "9*10^-6/K \| 25 – 100 ºC; 9.4*10^-6/K \| 25 – 200 ºC; 9.7*10^-6/K \| 25 – 300 ºC" | Good: LPBF Ti64, EOS M 290, 40 µm. The excerpt gives no build direction and no heat-treatment state for the CTE. | no |
| alphaZ | not found | — | — | — | — | — |
| maxServiceTempC | 350 °C | https://www.carpentertechnology.com/hubfs/7407324/Material%20Saftey%20Data%20Sheets/Ti%206Al-4V.pdf | Carpenter Technology, "Titanium Alloy Ti 6Al-4V" data sheet | "Ti 6Al-4V is recommended for use at service temperatures up to approximately 350°C (660°F)." | **Mismatch: wrought Ti-6Al-4V**, not LPBF. Other supplier sheets say 400 °C (750 °F), e.g. Finetubes, Superior Tube. 350 °C is the lower (conservative) value. | no |
| tempDerating | not found | — | — | — | — | — |

### 3.2 AlSi10Mg-LPBF

| Key | Value | URL | Document | Quote | Condition match | Opened |
|---|---|---|---|---|---|---|
| alpha | 20e-6 1/K | https://www.eos.info/metal-solutions/data-sheets/all-processes-and-materials?id=eos-aluminium-alsi10mg (also https://www.eos.info/var/assets/03_system-related-assets/material-related-contents/metal-materials-and-examples/metal-material-datasheet/aluminium/material_datasheet_eos_aluminium-alsi10mg_en_web.pdf) | EOS, "EOS Aluminium AlSi10Mg" material data sheet (page status 03.10.2026), CTE per ASTM E228 | about 20 × 10⁻⁶/K over 25–100 °C, 22 × 10⁻⁶/K over 25–200 °C, 27 × 10⁻⁶/K over 25–300 °C (search excerpt, values paraphrased by the tool; confirm the exact row text) | Fair: LPBF AlSi10Mg (EOS). The sheet notes that values depend on build-platform temperature, job layout and position. The excerpt does not say as-built or stress-relieved; Anneal's material is "as built". | no |
| alphaZ | not found | — | — | — | — | — |
| maxServiceTempC | not found | — | — | — | — | — |
| tempDerating | not found | — | — | — | — | — |

Cross-check (not used): AddUp AlSi10Mg sheet, https://addupsolutions.com/wp-content/uploads/2023/10/AlSi10Mg-Material-Data-Sheet.pdf, "21 µm/(m·°C)" for 20–100 °C, from literature (not measured).

### 3.3 316L-LPBF

| Key | Value | URL | Document | Quote | Condition match | Opened |
|---|---|---|---|---|---|---|
| alpha | 15.72e-6 1/K | https://www.eos.info/metal-solutions/data-sheets/stainlesssteel/pds-eos-stainlesssteel-316l-4441-eos-m-290-20um | EOS, "PDS EOS StainlessSteel 316L (4441) EOS M 290 20 µm", thermal properties | "CTE 15.72 *10^-6/K 16.75 *10^-6/K 17…" (first value 25–100 °C, second 25–200 °C per the excerpt) | Good: LPBF 316L, EOS M 290. Powder 316L-4441 at 20 µm; the excerpt does not say the test standard or heat-treatment state. | no |
| alphaZ | not found | — | — | — | — | — |
| maxServiceTempC | not found | — | — | — | — | — |
| tempDerating | not found | — | — | — | — | — |

### 3.4 PA12-SLS

| Key | Value | URL | Document | Quote | Condition match | Opened |
|---|---|---|---|---|---|---|
| alpha | 109e-6 1/K | https://www.sculpteo.com/static/0.30.0-49/documents/materials/polyamide_PA2200/PA2200_Product_information_03-10_en.pdf | EOS, "PA 2200 Product Information" (03.10), thermal properties | "Coefficient of linear thermal expansion ISO 11359 / DIN 53752-A x10^-4 /K 1.09" | Good: laser-sintered PA12 (EOS PA 2200). Sheet dated 2010; values for PA12 stored at 23 °C / 50 % RH. No direction given. A different PA12 process (Stratasys SAF) gives 160 µm/(m·°C), ASTM E831: https://www.stratasys.com/contentassets/09b8f05c09914d40a96127cc609978cd/mds_saf_pa12_0724a.pdf | no |
| alphaZ | not found | — | — | — | — | — |
| maxServiceTempC | 86 °C (HDT at 1.82 MPa) | https://www.materialise.com/en/industrial/3d-printing-materials/pa12-sls | Materialise, "PA 12 (SLS) for Laser Sintering", datasheet table | "Heat deflection temperature ASTM D648 (@1.82 MPa) · 86 · °C" | Good: SLS PA12. Quantity: **HDT/A**. Other values seen (not used): Vicat 163 °C (ISO 306, 50 N) and HDT 86 (ISO 75) on Makerverse SLS-PA12, https://makerverse-static.s3.eu-central-1.amazonaws.com/datasheets/SLS-PA12_MV.pdf; Vicat A 181 °C (Forerunner PA 2200 page). | no |
| tempDerating | not found | — | — | — | — | — |

### 3.5 PLA-FDM

| Key | Value | URL | Document | Quote | Condition match | Opened |
|---|---|---|---|---|---|---|
| alpha | not found | — | — | — | — | — |
| alphaZ | not found | — | — | — | — | — |
| maxServiceTempC | 58.8 °C (HDT at 0.455 MPa) | https://um-support-files.ultimaker.com/materials/2.85mm/tds/PLA/Ultimaker-PLA-TDS-v5.00.pdf | UltiMaker, "Ultimaker PLA Technical data sheet" v5.00, thermal properties | "heat deflection (HDT) at 0.455 MPa (ISO 75-2 / B) at 58.8 ± 0.4 °C, and a glass transition of 59.1 °C (ISO 11357, DSC, 10 °C/min)" (search excerpt, paraphrased by the tool) | Good: FDM PLA filament. Quantity: **HDT/B**; HDT/A not in this sheet. PLA is amorphous as printed, so HDT/B ≈ Tg (section 2, rule). | no |
| tempDerating | not found | — | — | — | — | — |

### 3.6 PETG-FDM

| Key | Value | URL | Document | Quote | Condition match | Opened |
|---|---|---|---|---|---|---|
| alpha | 51e-6 1/K | https://productcatalog.eastman.com/tds/ProdDatasheet.aspx?product=71040786&pn=Eastar+676 | Eastman, "Eastar™ copolyester 6763" technical data sheet | "Coefficient of Linear Thermal Expansion · D 696 · 5.1 x 10^-5 /°C" | **Mismatch: bulk PETG resin** (injection-moulded test bars), not printed PETG filament. Filament brands differ in formulation. ISO-based MatWeb entry for the same resin gives 77 (flow) and 83 (transverse) µm/(m·°C). Use with this note, or replace with a filament value when one is found. | no |
| alphaZ | not found | — | — | — | — | — |
| maxServiceTempC | 68 °C (HDT, ISO 75) | https://prusament.com/wp-content/uploads/2022/10/PETG_Prusament_TDS_2021_10_EN.pdf (also https://www.prusa3d.com/file/2765253/prusament-petg-technical-data-sheet.pdf) | Prusa Research, "Prusament PETG Technical datasheet" v1.1 (16-02-2022) | "heat deflection temperature of 68 °C at 0.45 MPa, tested per ISO 75 … lists the heat deflection value at both 0.45 MPa and 1.80 MPa, each at 68 °C" (search excerpt, paraphrased by the tool) | Good: FDM PETG filament. Quantity: **HDT/A** (1.80 MPa), if the page confirms it; the equal A and B values are unusual — check. Bulk resin values (Eastman 6763): HDT 64 °C at 1.82 MPa, 70 °C at 0.455 MPa (ASTM D648), Tg about 80 °C (DSC), Vicat 85 °C. | no |
| tempDerating | not found | — | — | — | — | — |

### 3.7 Al6061-T6

| Key | Value | URL | Document | Quote | Condition match | Opened |
|---|---|---|---|---|---|---|
| alpha | 23.6e-6 1/K | https://asm.matweb.com/search/SpecificMaterial.asp?bassnum=MA6061T6 | ASM Aerospace Specification Metals, "Aluminum 6061-T6; 6061-T651" (MatWeb) | "CTE, linear · 23.6 µm/m-°C @Temperature 20.0 - 100 °C · 13.1 µin/in-°F" | Good: wrought 6061-T6 (Anneal's material is wrought, machined). | no |
| alphaZ | not applicable (isotropic wrought) | — | — | — | — | — |
| maxServiceTempC | not found | — | — | — | — | — |
| tempDerating | not found (yield only; see below) | — | — | — | — | — |

Yield at temperature (found, but **no E at temperature**, so no `tempDerating` row can be built):
MatWeb "Aluminum 6061-T6; 6061-T651", https://www.matweb.com/search/datasheet.aspx?MatGUID=1b8c06d0ca7c456694c7777d9e10be5b,
"AA; Typical" yield 276 MPa at 24 °C, 262 MPa at 100 °C, 214 MPa at 149 °C, 103 MPa at 204 °C,
34 MPa at 260 °C (search excerpt). The fall above 150 °C is steep. If the code owner finds a
sourced E(T) (for example MMPDS / MIL-HDBK-5 tables, not curves), these yield values give the
yield factors 1, 0.949, 0.775, 0.373.

### 3.8 Al7075-T6

| Key | Value | URL | Document | Quote | Condition match | Opened |
|---|---|---|---|---|---|---|
| alpha | 23.6e-6 1/K | https://asm.matweb.com/search/SpecificMaterial.asp?bassnum=MA7075T6 | ASM Aerospace Specification Metals, "Aluminum 7075-T6; 7075-T651" (MatWeb) | "CTE, linear 68F 23.6 µm/m-°C" (temperature range not clear in the excerpt; confirm it is 20–100 °C). The general MatWeb sheet https://matweb.com/search/DataSheet.aspx?MatGUID=4f19a42be94546b686bbf43f79c51b7d gives "23.4 µm/m-°C @Temperature 20.0 - 100 °C". | Good: wrought 7075-T6. | no |
| alphaZ | not applicable (isotropic wrought) | — | — | — | — | — |
| maxServiceTempC | not found | — | — | — | — | — |
| tempDerating | not found | — | — | — | — | — |

## 4. Ready-to-paste values (sourced only)

Merge each entry into the material of the same name in `MATERIALS` (`anneal/materials.py`). For
Al6061-T6 and Al7075-T6 the existing `source` text stays; append the thermal text to it. Before
pasting, do the check in section 1 (open each URL and confirm the number).

```python
# H2 thermal data. Each value: see docs/research/thermal-material-data.md (URL, document, quote).
# alpha is the mean CTE from about 20-25 C to 100 C. maxServiceTempC names its quantity in source.
THERMAL_DATA = {
    "Ti64-LPBF": {
        "alpha": 9.0e-6,
        "maxServiceTempC": 350.0,
        "source": "alpha: EOS Titanium Ti64 Grade 5 material data sheet (EOS M 290, 40 um), CTE 9.0e-6/K "
                  "at 25-100 C, ASTM E228, https://www.eos.info/metal-solutions/data-sheets/titanium/"
                  "pds-eos-titanium-ti64-grade5-eos-m-290-40um. maxServiceTempC: Carpenter Ti 6Al-4V data "
                  "sheet, 'service temperatures up to approximately 350 C' (wrought alloy, not LPBF), "
                  "https://www.carpentertechnology.com/hubfs/7407324/Material%20Saftey%20Data%20Sheets/Ti%206Al-4V.pdf",
    },
    "AlSi10Mg-LPBF": {
        "alpha": 20.0e-6,
        "source": "alpha: EOS Aluminium AlSi10Mg material data sheet, CTE about 20e-6/K at 25-100 C, ASTM E228 "
                  "(depends on platform temperature and job layout), "
                  "https://www.eos.info/metal-solutions/data-sheets/all-processes-and-materials?id=eos-aluminium-alsi10mg",
    },
    "316L-LPBF": {
        "alpha": 15.72e-6,
        "source": "alpha: EOS StainlessSteel 316L-4441, EOS M 290 20 um process data sheet, CTE 15.72e-6/K "
                  "at 25-100 C, https://www.eos.info/metal-solutions/data-sheets/stainlesssteel/"
                  "pds-eos-stainlesssteel-316l-4441-eos-m-290-20um",
    },
    "PA12-SLS": {
        "alpha": 109.0e-6,
        "maxServiceTempC": 86.0,
        "source": "alpha: EOS PA 2200 Product Information (03.10), coefficient of linear thermal expansion "
                  "1.09e-4/K, ISO 11359, https://www.sculpteo.com/static/0.30.0-49/documents/materials/"
                  "polyamide_PA2200/PA2200_Product_information_03-10_en.pdf. maxServiceTempC = HDT at 1.82 MPa "
                  "(ASTM D648) 86 C, short-term, Materialise PA 12 (SLS) datasheet, "
                  "https://www.materialise.com/en/industrial/3d-printing-materials/pa12-sls",
    },
    "PLA-FDM": {
        "maxServiceTempC": 58.8,
        "source": "maxServiceTempC = HDT at 0.455 MPa (ISO 75-2/B) 58.8 C, short-term (Tg 59.1 C, DSC), "
                  "Ultimaker PLA TDS v5.00, "
                  "https://um-support-files.ultimaker.com/materials/2.85mm/tds/PLA/Ultimaker-PLA-TDS-v5.00.pdf. "
                  "alpha: no sourced value; add a measured or datasheet value.",
    },
    "PETG-FDM": {
        "alpha": 51.0e-6,
        "maxServiceTempC": 68.0,
        "source": "alpha: Eastman Eastar copolyester 6763 TDS, 5.1e-5/C, ASTM D696 (bulk resin, not printed "
                  "filament), https://productcatalog.eastman.com/tds/ProdDatasheet.aspx?product=71040786&pn=Eastar+676. "
                  "maxServiceTempC = HDT (ISO 75, 1.80 MPa) 68 C, short-term, Prusament PETG TDS v1.1, "
                  "https://prusament.com/wp-content/uploads/2022/10/PETG_Prusament_TDS_2021_10_EN.pdf",
    },
    "Al6061-T6": {
        "alpha": 23.6e-6,
        "source": "alpha: ASM Aerospace Specification Metals, Aluminum 6061-T6, CTE 23.6 um/m-C at 20-100 C, "
                  "https://asm.matweb.com/search/SpecificMaterial.asp?bassnum=MA6061T6",
    },
    "Al7075-T6": {
        "alpha": 23.6e-6,
        "source": "alpha: ASM Aerospace Specification Metals, Aluminum 7075-T6, CTE 23.6 um/m-C, "
                  "https://asm.matweb.com/search/SpecificMaterial.asp?bassnum=MA7075T6",
    },
}
```

No `alphaZ` and no `tempDerating` entry is in the block. No source with those values was found
(section 5).

## 5. Gaps (no value; leave the key out)

| Material | Key | What was searched |
|---|---|---|
| all eight | alphaZ | EOS datasheets (one CTE, no direction); "Coefficient of Thermal Expansion of AlSi10Mg, 316L Stainless Steel and Ti6Al4V Alloys Made with Laser Powder Bed Fusion", Materials 18 (2025) 4468, https://doi.org/10.3390/ma18194468 (directional values not in the excerpt — **best lead for the LPBF metals; open the full text**); "Effect of Build Orientation on Thermal Expansion of LPBF Printed Ti-6Al-4V", https://link.springer.com/article/10.1007/s11661-025-07706-7 (differences only reported at 850–1000 °C); FBG study of printed polymers, Materials 17 (2024) 4668, https://doi.org/10.3390/ma17184668 (0°/90° raster values for PEBA and CF-PA only in the excerpt; PLA value not seen). Wrought aluminium is isotropic: alphaZ not needed. |
| PLA-FDM | alpha | Ultimaker PLA and Tough PLA TDS (CTE row is "-"); NatureWorks Ingeo (values behind a login on SpecialChem); Rădulescu et al., Polymers 14 (2022) 3061, https://doi.org/10.3390/polym14153061 (PLA value not in the excerpt — **open the full text**); Botean, E3S Web Conf. 32 (2018) 01007, https://doi.org/10.1051/e3sconf/20183201007 (PLA value not in the excerpt); TMA study PMC10006872 (range 71–277 ppm/K across directions and curves; not usable as one value); a retailer blog (68e-6/°C, no test standard; rejected). |
| PETG-FDM | alpha (filament) | Prusament PETG TDS (no CTE in the excerpt). The Eastman bulk value is used with a mismatch note. |
| Ti64-LPBF | tempDerating | Searched LPBF Ti-6Al-4V hot tensile data at 200–400 °C. Found only: EBM Ti-6Al-4V after HIP, Materials 15 (2022) 3624, https://doi.org/10.3390/ma15103624, abstract: "at 350 °C, the yield strength decreased to about 65% compared to the room-temperature strength" — EBM not LPBF, approximate, and no E. DLD Ti-6Al-4V, PMC8585263: yield "decreases gradually by 40%" to 500 °C — DLD, no table seen. |
| AlSi10Mg-LPBF | maxServiceTempC, tempDerating | EOS datasheets (no limit). "High-Temperature Mechanical Properties of Stress-Relieved AlSi10Mg Produced via LPBF", PMC9612077 (tests at RT, 125, 250, 450 °C; excerpt gives UTS 280.2 / 162.8 / 34.4 MPa at RT / 250 / 450 °C, not yield or E; stress-relieved 2 h at 350 °C, not as-built — **open the full text, Table A1**). |
| 316L-LPBF | maxServiceTempC, tempDerating | EOS datasheets (no limit). Dryepondt et al., "Microstructure and high temperature tensile properties of 316L fabricated by laser powder-bed fusion", Addit. Manuf. (ORNL), https://www.osti.gov/pages/biblio/1817598 (20–700 °C; no table in the excerpt — **best lead; OSTI full text is public**). |
| PA12-SLS | tempDerating | Searched SLS PA12 tensile tests at 50–80 °C. Found a creep/visco-plastic study up to 110 °C (ScienceDirect S0142941816310315, paywalled) and room-temperature studies only. |
| PLA-FDM | tempDerating | Grasso et al., "Effect of temperature on the mechanical properties of 3D-printed PLA tensile specimens", Rapid Prototyping J. (2018), https://doi.org/10.1108/RPJ-04-2017-0055 (modulus at 30–60 °C; only "1400 ± 78" at 30 °C was visible and its column was unclear; no 20 °C row — **open Table 3**). A 2025 J. Mater. Eng. Perform. study (25, 55, 85, 115 °C), https://link.springer.com/article/10.1007/s11665-025-11754-w (strength only in the excerpt). |
| PETG-FDM | tempDerating | No temperature-dependent tensile data for printed PETG found. |
| Al6061-T6 | maxServiceTempC, tempDerating | No supplier service limit. Yield at temperature found (section 3.7) but no E at temperature. MMPDS / MIL-HDBK-5 give E(T) as curves; reading values from a curve is an estimate and was not done. |
| Al7075-T6 | maxServiceTempC, tempDerating | MatWeb excerpt gave temperatures in the ultimate-strength block only, and the excerpt was not consistent; not used. |

## 6. Check of the existing room-temperature values (not changed)

| Material | Anneal value | Source value | Source | Result |
|---|---|---|---|---|
| Ti64-LPBF | E 110000 MPa | 110 GPa (heat treated, 60 µm process) | EOS PDS Ti64 M 290 60 µm, https://www.eos.info/metal-solutions/data-sheets/titanium/pds-eos-titanium-ti64-eos-m-290-60um | match |
| Ti64-LPBF | yield 880 MPa | Rp0.2 945–1020 MPa heat treated (30/40/60/80 µm processes); 900–920 MPa after HIP | EOS PDS Ti64 M 290 (30, 40, 60, 80 µm pages) | **mismatch: Anneal is 7–14 % lower** (conservative). The note says "stress relieved"; EOS gives "heat treated". |
| Ti64-LPBF | density 4.43 | ≥ 4.4 g/cm³ (40 µm); 4.41 g/cm³ (older sheet) | EOS Ti64 Grade 5 MDS | match within 0.5 % |
| AlSi10Mg-LPBF | yield 230 MPa | as built: 233 (vertical) / 270 (horizontal) MPa (30 µm); 240 / 250 (60 µm) | EOS AlSi10Mg MDS | match (Anneal ≈ the lower, vertical value) |
| AlSi10Mg-LPBF | density 2.67 | ≥ 2.66; 2.67 g/cm³ | EOS AlSi10Mg MDS / FlexLine sheet | match |
| AlSi10Mg-LPBF | E 70000 MPa | not in the excerpts | — | not checked |
| 316L-LPBF | yield 470 MPa | as manufactured 490 (V) / 530 (H) MPa (40 µm); other revision 500 / 570 MPa | EOS PDS 316L-4404 M 290 40 µm; 316L-4441 page | **mismatch: Anneal is 4–17 % lower** (conservative) |
| 316L-LPBF | E 190000 MPa | EOS gives no modulus ("-"). One study: 198 GPa horizontal, 158.7 GPa vertical (PMC8658429) | — | not checked against a datasheet; note the anisotropy |
| 316L-LPBF | density 7.95 | ≥ 7.97 g/cm³ (ISO 3369) | EOS PDS 316L-4441 20/40 µm | small mismatch (0.3 %) |
| PA12-SLS | E 1700 MPa | 1700 MPa (X/Y), 1650 MPa (Z) | EOS PA 2200 product information | match |
| PA12-SLS | yield 48 MPa | tensile strength 48 MPa (X/Y), 47 (Z) | EOS PA 2200 product information | match (PA12 sheets give tensile strength, not a yield point) |
| PA12-SLS | density 1.01 | 0.93 g/cm³ laser-sintered part (0.90–0.95 older sheet) | EOS PA 2200 MDS, https://www.sculpteo.com/media/data/faq/pa2200-datasheet.pdf | **mismatch: Anneal is 9 % high** (1.01 is the solid, moulded PA12 value). Mass and self-weight are 9 % high. |
| PLA-FDM | E 3500 MPa | 3250 ± 119 (XY), 3292 (YZ), 3071 (Z) MPa, ASTM D3039 | Ultimaker PLA TDS v5.00 | **mismatch: Anneal is 8 % high** in the layers, 14 % high across them |
| PLA-FDM | yield 50 MPa | tensile stress at yield 52.5 (XY), 59.0 (YZ) MPa; Z: no yield, break 33.1 MPa | Ultimaker PLA TDS v5.00 | match (Anneal 5 % lower); the note on Z strength agrees |
| PLA-FDM | density 1.24 | 1.24 g/cm³ | Ultimaker PLA TDS v5.00 | match |
| PETG-FDM | yield 45 MPa | 47 ± 2 MPa (horizontal), 50 ± 1 MPa (xz), ISO 527-1 | Prusament PETG TDS v1.1 | match (Anneal 4 % lower) |
| PETG-FDM | E 2000 MPa | standard Prusament PETG: not in the excerpt; Prusament PETG *Recycled*: 1.5 / 1.6 GPa | — | not checked (only a different product seen; it would mean Anneal is 25 % high) |
| Al6061-T6 | E 68900, yield 276, density 2.70 | 68.9 GPa, 276 MPa (AA typical) | ASM MA6061T6 | match |
| Al7075-T6 | E 71700, yield 503, density 2.81 | 71.7 GPa, 503 MPa, 2.81 g/cm³ | ASM MA7075T6 | match |

## 7. Next steps for the owner

1. Allow the hosts in the environment network settings (`www.eos.info`, `asm.matweb.com`,
   `www.matweb.com`, `um-support-files.ultimaker.com`, `prusament.com`, `www.materialise.com`,
   `productcatalog.eastman.com`, `www.carpentertechnology.com`, `pmc.ncbi.nlm.nih.gov`,
   `www.osti.gov`, `doi.org`), then open each URL and confirm the quotes (section 1).
2. Open the four "best lead" full texts in section 5 for alphaZ and derating tables.
3. For PLA and PETG, a measured CTE of the owner's own filament is better than any literature
   value (strip in an oven, caliper, 20 → 50 °C).
