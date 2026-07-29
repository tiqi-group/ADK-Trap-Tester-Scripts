# Interface layout schema v2

Status: **implemented.** This documents the schema as built.

**v1 is not supported.** The loader accepts schema 2 only and rejects anything else
with a message pointing at the generator. The project has had no release, so there
is nothing to stay compatible with, and a loader that speaks exactly one format is
the point of the exercise. The v1 upgrade path and the one-shot migration tool
existed only long enough to convert the existing files, and have been removed; they
are in the git history if a legacy file ever turns up.

This replaces the v1 layout JSON (`InterfaceLayout` in
`src/trap_tester/core/layout/interface.py`) and the cross-interface mapping CSV
(`mapping.py`). The goal is not new features: it is to move meaning *into the
data* so the parser stops inferring it, and to collapse every special case into a
single upgrade function that runs once at load.

## Principles

1. **One address, one name.** `(connector, pin)` is the apparatus' electrical
   address — mandatory on every slot of every layout. It is a property of the
   physical apparatus, not of the tester, so it is meaningful when debugging a
   running system with no tester attached. `ident` is the slot's free-form name on
   *its own* interface (`A01`, `287`, `WZ_DCL3_6`) — opaque at match time.
2. **Roles are declared, never inferred from colour.** No code may recover
   meaning by comparing hex fills.
3. **No stored `channel`.** The mux signal is derivable and is derived.
4. **Setup wiring lives only in the mapping CSV.** A layout carries its *nominal*
   wiring; a CSV overrides it.
5. **One format.** `from_dict` accepts schema 2 and nothing else, so no code path
   anywhere has to reason about an older shape.

## Why: the v1 exceptions this removes

| v1 exception | Where | v2 answer |
|---|---|---|
| Decoration class recovered by matching hex fills, and only on `Circle` | `layout_canvas.py:292-301` | `Slot.class` (§2.2) |
| `background` conflates chrome with real channel-less pads | `interface.py:208`, `interposer.py:99`, `iontrap.py:89-99` | non-signal pads move into `slots`; `background` is chrome only (§2.3) |
| `channel` means three different things | see below | field deleted (§2.2) |
| `apply_to` branches 3 ways and guesses the column by "best ident overlap" | `mapping.py:132-153, 208-226` | `match_by` + `slug` are declared (§2.1, §3) |
| `key_by` is a closed enum that `from_dict` raises on | `interface.py:50,222` | `pin_space` is an open string (§2.1) |
| Connector/pin column spellings listed twice, incl. the typo `N Connecgor` | `iontrap.py:44`, `mapping.py:45-51` | one header normaliser + a one-time CSV rewrite (§3) |
| `_PIN_MODULO = 100` baked into the parser | `mapping.py:56` | normalised out of the data once (§5) |
| Geometry stored two ways (flat `x/y/r/rot/shape` vs `shapes[]`) | `interface.py:157-162` | `shapes[]` always, ≥1 entry (§2.2) |

The three incompatible meanings of `channel`, for the record — this is the field
most worth deleting:

| Layout | slots | distinct `channel` | meaning |
|---|---|---|---|
| `dsub50`, `Bondfinger`, `interposer` | 50 / 352 / 384 | 50 / 48 / 48 | mux signal *within* a connector (`dsub_to_signal`) |
| `hawk1-3`, `flatland` | 193 / 338 / 340 / 94 | one per slot | a counter the importer invents (`iontrap.py:18-19`) |
| `interposer_BePe` | 174 | **0 — all null** | nothing; relies wholly on the CSV |
| after `apply_to` | — | one per net | the mapping's `net_id` |

## 2. Layout JSON v2

### 2.1 File level

| field | type | required | notes |
|---|---|---|---|
| `schema` | int | yes | `2`. Absent ⇒ v1. |
| `name` | str | yes | display name only; may be renamed freely |
| `slug` | str | yes | **stable** key, independent of filename and display name. Lowercase `[a-z0-9_]`. A mapping CSV column header must equal this. |
| `match_by` | str | yes | `"connector_pin"` for tester reference interfaces (DSUB-50, FPC); `"ident"` for named ones (trap, interposer, bond-finger). Replaces `_match_mode`'s guess. |
| `pin_space` | str | yes | which numbering `pin` is in: `"dsub_pin"`, `"fpc_conductor"`, … Open string; used for hover text and for cross-space bridging. No longer a closed enum. |
| `units` | str | yes | `"mm"` or `"grid"` |
| `pitch_mm` | float | no | grid pitch, when `units == "grid"`. Lets a grid layout later be placed in mm. |
| `background` | list | yes | chrome only — see §2.3 |
| `slots` | list | yes | every pad, signal or not — see §2.2 |

> **Revision to what I proposed earlier.** I had said "canonicalise everything to
> mm at generation time". That was wrong: the interposer's coordinates are in pad
> pitches and we do not know the physical pitch. Inventing one would be a silent
> lie about a dimension. So `units` stays declared, with an optional `pitch_mm` to
> be filled in when someone actually knows it. Nothing derives physical size from
> `units` today; it is honest metadata rather than a conversion trigger.

### 2.2 `Slot`

| field | type | required | notes |
|---|---|---|---|
| `connector` | int | yes | apparatus connector |
| `pin` | int | yes | pin within `pin_space`, **physical** (1..50 for `dsub_pin`) — no hundreds-digit encoding |
| `ident` | str \| null | yes when `match_by == "ident"` | opaque at match time; must not contain a comma |
| `class` | str | no, default `"signal"` | `"signal"`, `"gnd"`, `"rf"`, `"loopback"`, `"sensor_heater"`, `"axialisation"`. Only `"signal"` is measurable/clickable. An unknown class still renders, in a grey fallback. |
| `label` | str \| null | no | in-shape text; `null` ⇒ fall back to `ident`, then `pin`; `""` hides |
| `shapes` | list[SlotShape] | yes, ≥1 | the slot's drawn geometry |
| ~~`channel`~~ | — | **removed** | derived from `(connector, pin)` + `pin_space` |
| ~~`x`,`y`,`r`,`rot`,`shape`~~ | — | **removed** | always expressed as one `shapes` entry |

The slot's hover/label anchor is computed from `shapes` (bounding-box centre), as
`SlotShape.from_polygon` already does — it is not stored.

`SlotShape` is unchanged from v1: `shape` (`circle`/`rect`/`finger`/`poly`),
`x`, `y`, `r`, `rot`, and `points` for `poly`.

**Deriving the mux signal.** One function, one place:
`signal_for(connector, pin, pin_space)` → `dsub_to_signal` for `"dsub_pin"`,
`signal_to_fpc`'s inverse for `"fpc_conductor"`. Generators are forbidden from
stamping a channel. This is what makes DSUB ↔ FPC correlation work without a
stored field, and it is why `iontrap.py`'s invented counter disappears.

### 2.3 `background` — chrome only

Primitives keep their geometry (`circle`/`rect`/`line`/`polyline`/`text`) and gain:

| field | type | notes |
|---|---|---|
| `style` | str | `"outline"` (DSUB shell, FPC ribbon), `"caption"`, `"grid_label"` |

and **lose** `fill`, `stroke`, `color`, `width`. No hex in the JSON at all.

### 2.4 Styling

Colours resolve at draw time from one table keyed by `Slot.class` (pads) and
`background.style` (chrome). Two consequences: the RF-legend bug disappears
(legend entries come from the `class` values present, for *any* shape — v1 only
looked at `Circle`, so `iontrap`'s `Polyline` RF rails could never appear), and
layouts become theme-aware, which today they are not — every colour is hardcoded
light-mode hex.

## 3. Mapping CSV v2

```
connector,pin,flatland,interposer_bepe
0,1,WZ_DCL3_6,L13
0,2,IZ1_DCL1_2,N04
```

- **Reserved headers** `connector` and `pin`. Recognised through one normaliser
  (casefold; collapse spaces/underscores/hyphens) — so `Connector`, `DSUB_Pin`,
  `N Connecgor` all resolve, in *one* place instead of two hand-kept lists.
- **Every other header is a layout `slug`.** Not a display name.
- One row per net. A cell holds that net's `ident` on that interface, or is blank.
- Several idents in one cell are separated by `;` (not `,` — commas are excluded
  from idents by rule, and the loader **rejects** any ident containing one, so it
  stays true).
- `pin` is physical, 1..50.

### Matching

| layout `match_by` | join |
|---|---|
| `"ident"` | layout slot `ident` ↔ the cell in the column named by the layout's `slug` |
| `"connector_pin"` | layout slot `(connector, pin)` ↔ the row's `(connector, pin)` |

A net re-stamps the matched slot's `(connector, pin)`. Slots matching no net keep
their nominal wiring.

### Ident normalisation — strict, and loud

1. Strip leading/trailing whitespace. Nothing else.
2. Match case-sensitively. On failure, retry case-insensitively; on a hit,
   **succeed but warn**, naming the cell — the join is not blocked, and the data
   gets fixed.
3. No numeric normalisation: `N04` ≠ `N4`. Any rule clever enough to equate those
   will eventually mangle `LZ_DC1_2_COW`, and a wrong silent match is worse than a
   reported miss.

`coverage()` (`mapping.py:178`) becomes a three-way diff — matched / layout-only /
CSV-only — surfaced where the current warning banner goes. Concretely, it would
immediately report that `interposer_BePe`'s column names only **92** of its
**174** pads, i.e. 82 pads are silently unwired today.

### Annotations

Marks key on `(connector, pin)`, not on a channel. A mark means "this physical
pin is suspicious" — a fact that survives loading a different CSV. The mapping
changes *which geometry is drawn* at that pin; the mark stays put.

## 4. What the conversion did (historical)

The existing files were converted once, in place, and the tooling then deleted. Kept
here because it records what changed in the data:

* every layout: `channel` dropped, geometry folded into `shapes`, colours replaced by
  a `style`/`class` name, `key_by` renamed to `pin_space`, a `slug` and `match_by`
  added.
* `hawk1-3`: pins carried a hundreds-digit connector bank (up to 150), stripped to
  the physical 1..50.
* `flatland`, `interposer_BePe`: every slot was at `(connector 0, pin 0)` — a
  placeholder, so all of them collided on one address. They were given synthetic
  addresses (§2.2), which is what made the conversion purely mechanical; without
  that these two would have had to be regenerated from source first.
* ion-trap RF rails and interposer GND/loopback/sensor pads were background
  primitives whose *fill colour* was their only record of what they were; they became
  slots with a declared `class`. Polygons as well as circles — v1's colour-matching
  legend only looked at circles, so trap RF rails could never appear in one.
* `interposer.json` was **regenerated** rather than converted: v1 wrote its 12
  `axialisation` pads in the grey unknown-type fallback, so that class is not
  recoverable from the file. (`axialisation` was in
  `docs_tmp/interposer_flavor.csv` all along and had no entry in v1's colour table,
  so those pads were silently grey and absent from every legend.)
* both mapping CSVs: headers canonicalised (`Connector`/`DSUB_Pin` → `connector`/
  `pin`), interface columns renamed to layout slugs — including `Electrode` →
  `flatland`, which could only be resolved by ident overlap — and 172 of
  `mapping_buzzard.csv`'s 340 pins stripped of their bank digit.

Result: all 9 layouts are schema 2, contain no hex, and have **zero duplicate
addresses**.

## 5. Behaviour changes worth knowing

* **Label fallback inverted.** v1 drew the pin number and fell back to `ident` only
  when `label` was `""`. v2 falls back to `ident` first, then the pin — on a trap or
  an LGA the electrode/pad name is what an operator reads, and the pin is nominal.
* **DSUB <-> FPC correlation is derived, not stamped.** v1 kept the two JSON files in
  agreement by writing a matching `channel` into both. They can no longer drift.
* **Colours are resolved at load.** A primitive stores a `style` name; the concrete
  `fill`/`stroke`/`width`/`color`/`size` are set from the style table when it is
  built, so renderers keep reading `prim.fill` and no layout file contains hex.

## 6. Deferred

- `pitch_mm` for `interposer` / `interposer_BePe` — needs the real LGA pitch.
- `mapping_goshawk.csv` / `mapping_sparrow.csv` (`docs_tmp/traps`) are not yet
  imported as mappings; presumably the `hawk1` / `hawk2` counterparts to
  `mapping_buzzard.csv`.
- Multi-ident (`;`) cells: parsed and tested, but no generator emits them yet.
- The `axialisation` legend colour is a guess (purple); nothing in the source data
  specifies one.
