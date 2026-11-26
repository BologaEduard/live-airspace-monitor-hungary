---
name: Airspace
description: "Night atlas: cool paper, deep chart surfaces, precise evidence."
colors:
  paper: "#f2f5f6"
  surface: "#fff"
  ink: "#182d40"
  muted: "#526879"
  border: "#dce4e8"
  chart: "#152b3b"
  amber: "#e5b664"
  coral: "#b45e42"
  flight-high: "#dceff6"
  flight-low: "#79b5cb"
  flight-unknown: "#a7b4c2"
  trail: "#82b9cf"
  focus: "#367a99"
typography:
  headline:
    fontFamily: "'Manrope Variable', sans-serif"
    fontSize: "clamp(28px, 2.6vw, 38px)"
    fontWeight: 750
    lineHeight: 1.2
    letterSpacing: "-.035em"
  title:
    fontFamily: "'Manrope Variable', sans-serif"
    fontSize: "27px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-.035em"
  body:
    fontFamily: "'Manrope Variable', sans-serif"
    fontSize: "14px"
    lineHeight: 1.75
  label:
    fontFamily: "'Manrope Variable', sans-serif"
    fontSize: "13px"
    fontWeight: 650
  measurement:
    fontFamily: "'Manrope Variable', sans-serif"
    fontSize: "23px"
    fontWeight: 650
    letterSpacing: "-.025em"
rounded:
  panel: "14px"
  field: "6px"
  control: "8px"
spacing:
  inline: "8px"
  control-gap: "10px"
  compact: "12px"
  group: "16px"
  panel-gap: "22px"
  inset: "24px"
components:
  button-play:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    size: "38px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "5px"
    padding: "9px 7px"
  input-search:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "4px"
    height: "38px"
  select-aircraft:
    backgroundColor: "#fafcfc"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "10px 28px 10px 11px"
    width: "100%"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
  tag-local:
    textColor: "{colors.muted}"
    rounded: "{rounded.field}"
    padding: "7px 11px"
  marker-selected:
    textColor: "{colors.amber}"
    backgroundColor: "#e5b66416"
    rounded: "50%"
    size: "32px"
---

# Design System: Airspace

## Overview

**Creative North Star: "Night atlas"**

Night atlas pairs cool paper surfaces with deep chart fields. Manrope provides a single, precise typographic voice; warm selection and restrained evidence color make state changes legible.

The material is flat and lightly bounded. Depth comes primarily from tonal separation, with small shadows reserved for floating controls and disclosures.

**Key Characteristics:**

- Cool paper and deep blue tonal separation.
- Amber selection and ice-blue observations.
- Compact controls with explicit focus and data-quality states.

## Colors

The palette combines cool neutral chrome, a deep chart field, ice-blue observations, and warm state accents. Frontmatter owns the normative color values.

### Primary

- **Chart blue** defines dark geographical and annotation surfaces.
- **Amber** identifies selected aircraft and their observed trails.

### Secondary

- **Flight high / flight low** distinguish the two altitude bands; **trail** carries background observed paths.
- **Coral** marks preliminary evidence candidates.

### Neutral

- **Paper** is the application background; **surface** is the white control and panel plane.
- **Ink**, **muted**, and **border** establish text hierarchy and thin divisions.
- **Flight unknown** supports a dashed ring, rather than assigning an unknown altitude to either altitude band.
- **Focus** is the keyboard focus outline color.

**The State Evidence Rule.** Pair state color with text, shape, or selection semantics; missing altitude retains its dashed ring even under selection.

## Typography

Self-hosted Manrope Variable, with sans-serif fallback, is used throughout. No separate display or monospace family is implemented. The frontmatter roles describe actual desktop rules rather than a proposed complete type scale.

The headline is the page title; the title is selected identity; body describes evidence; labels serve compact controls; measurement emphasizes telemetry. Timestamps and measurements use tabular numerals. Supporting prose ranges from compact labels to readable evidence with generous line spacing. The page title becomes fixed at 28px at the compact layout; measurement sizes change with available space.

## Layout

The current web expression has a maximum shell width of 1860px, with fluid horizontal insets `clamp(20px, 3.2vw, 52px)`. Its desktop workspace uses a flexible primary area, a 318px companion panel, and a 22px gap. At 1600px the companion grows to 355px; at 1100px it narrows to 290px with a 16px gap. At 780px the workspace stacks, and at 500px controls wrap and shell insets narrow to 12px. These are observed web layouts, not requirements for every future surface.

The chart height is `clamp(390px, 51vh, 620px)` on desktop, 450px at the stacked breakpoint, and 300px at the narrow breakpoint. Compact chart annotations use opaque chart-colored bands so paths do not compete with text. Secondary geographic labels are reduced on compact screens.

## Elevation & Depth

White surfaces against cool paper and the dark chart provide structural depth. Thin borders separate panels. Shadows are limited to the chart control group (`0 3px 10px #05121c2b`), the data disclosure (`0 8px 32px #122d4121`), and aircraft icon drop shadows (`0 2px 2px #071724a0`).

Arrival uses a 450ms fade with a 4px translation and the shared easing curve. Evidence chevrons rotate over 180ms. Map fitting takes 650ms when animation is permitted. Reduced-motion preference removes arrival and transitions and makes map fitting immediate.

## Shapes

Panels use the panel radius; field controls and tags use the field radius; the play control uses the control radius. Quiet buttons are gently rounded at 5px. Aircraft targets are circular, with selection expressed through color, a translucent fill, and an outline. Borders remain thin. These differentiated radii are intentional; there is no universal pill treatment.

## Components

### Buttons

The dark square play button is the filled action. Quiet buttons stay transparent until hover, when a pale blue-gray background appears. The follow control uses a pale selected background and darker blue text. Disabled controls lower opacity to .45. Global keyboard focus is a 3px outline offset by 4px; selected aircraft use amber focus.

### Inputs / Fields

Search is borderless on a white toolbar, with a slash shortcut hint on wider screens. Select fields use a thin border, pale fill, and inline SVG chevron. Search and selection retain native semantics and visible keyboard focus.

### Navigation

Compact text navigation and inspector tabs use a 3px bottom indicator for the current item, with muted inactive text. The inspector tab bar stays visible while its panel scrolls. Navigation and tabs are separate implemented components, not interchangeable interaction patterns.

### Chips / Tags

The local-preview tag is a small outlined rectangle. The evidence count is a compact, softly rounded neutral badge. Neither is an interactive filter chip.

### Cards / Containers

White panels use thin cool borders and the panel radius. Inner content is grouped using spacing and dividers rather than nested elevated cards. The quality note has a pale blue-gray fill; stale quality uses a warm tinted fill and explicit wording.

### Aircraft and observed trails

Aircraft targets remain 32px; their SVG is 22px on desktop. At 780px and below, unselected SVGs shrink to 14px while selected ones remain 22px. Stale markers use .45 opacity. Unknown altitude has a dashed ring; unknown track uses a nondirectional circular symbol. Background trails use a 1px stroke at .32 opacity, reduced to .1 on compact screens. Selection uses a 2.1px amber trail at .95 opacity. These chart details describe the present signature component, not a generic chart theme.

### Evidence disclosure

Candidate entries use thin separators, a coral warning SVG, a bold compact heading, timestamp metadata, and an expanding evidence body. The disclosure chevron rotates when open. Physical evidence and limitations stay associated within the same disclosure.

## Do's and Don'ts

### Do:

- **Do** keep selection amber and evidence indicators coral.
- **Do** retain tabular numerals for measurements and timestamps.
- **Do** retain visible focus, reduced-motion support, and explicit unavailable states.

### Don't:

- **Don't** represent missing telemetry as zero or a normal status.
- **Don't** remove the dashed missing-altitude ring when an aircraft is selected.
- **Don't** use aircraft rotation to imply a known track when track is unavailable.
