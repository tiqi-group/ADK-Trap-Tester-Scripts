# Interfaces

The Interfaces panel is a notepad for wiring faults. When an operator reports that
some channels of a trap seem dead, mark those pins here, then switch to another
interface (the DSUB-50 feedthrough, the FPC ribbon, the interposer, the trap) to see
where the same signals run there. Marks made on one interface appear on every other,
so a pattern such as "all on one ribbon" or "all next to each other on the
interposer" becomes visible.

No hardware is needed; nothing here is measured.

## The panel

**Left: controls.**

* **Interface**
  * **Import…** adds a layout file; **Folders…** adds folders to search for layouts
    and mappings (see [Custom layouts and mappings](layouts.md)).
  * **Split view** shows a second interface next to the first.
  * **Mapping**: the wiring of your setup, and **Import…** to add a mapping CSV.
* **Annotations**
  * **Save…** and **Load…** store the marks in a JSON file and read them back.
  * **Clear all** removes every mark (after asking).
  * Below them, a count of the faulty and suspicious channels.

**Right: the interface visualiser.** The interface sketch, with that view's own
controls underneath it:

* **Interface**: which layout this view shows.
* **Connector**: which tester connector (0 to 7) to show, and **Show all** to tile
  every connector. Both apply only to the built-in DSUB-50 and FPC ribbon; a custom
  layout is drawn whole. With a mapping loaded, the connectors are the ones the
  mapping uses.

**Save view…** writes the visualiser to a PNG; in split view both sides go into one
image.

## Marking pins

Click a pad to cycle its mark:

**no comment → suspicious → faulty → no comment**

Only signal pads can be marked. Ground, RF and other non-signal pads (including the
ground shield conductors of the FPC ribbon) are drawn in their fixed colours, listed
in the legend, and ignore clicks.

A mark belongs to the **physical pin**, the tester connector and DSUB pin, not to a
spot on the picture. That is what makes it follow the signal: switch the interface or
connector and the marked pins light up wherever that signal is drawn. Changing the
mapping changes *where* a pin is drawn on the other interfaces; the mark stays on the
pin.

Zoom with the mouse wheel, pan by dragging, and double-click to see the whole
interface again. Pad labels appear as you zoom in, once there is room for them.
Hover over a pad for its name and address.

## Split view

Tick **Split view** to show two interfaces side by side, for example the DSUB-50 on
the left and the trap on the right. Each side has its own interface and connector
selectors under its canvas. Both sides share the same marks and the same mapping, so a
pin marked on one side changes colour on the other immediately. Drag the divider
between them if the two pictures have different shapes.

## Mappings

The built-in DSUB-50 and FPC ribbon are wired by the tester itself. Further along the
cabling (interposer, bond fingers, trap electrodes) the wiring depends on the setup,
so it is described by a **mapping CSV**: one row per net, saying what that net is
called on each interface. Select the mapping of your setup in **Mapping**; *Inherent
(no mapping)* uses the wiring stored in the layouts themselves. The format is
described in [Custom layouts and mappings](layouts.md#mapping-csv).

When a mapping does not fit the layout perfectly, a banner above the view says what
is wrong, so the data can be fixed:

* how many pads matched, and which pads or CSV entries found no partner;
* names that matched only when ignoring upper and lower case (they are used, but the
  CSV should be corrected);
* pads left on **placeholder addresses**: a layout that knows where its pads are, but
  not what they connect to, gives them made-up addresses so they can still be drawn
  and marked. Marks on them do not correspond to a physical pin until a mapping wires
  them.

If the mapping has nothing to do with the chosen layout, the banner says so and the
layout is shown with its own wiring.
