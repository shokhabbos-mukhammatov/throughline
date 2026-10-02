# Throughline design: the study desk

Throughline should feel like sitting down to study: a notebook open on the desk, the week's plan on a taped
slip, concept cards pinned up and joined with string. Every paper object means something. Nothing is there
only to look crafty.

The goal is a calm, focused, learning vibe. It isn't a scrapbook, and it isn't neobrutalism.

## The desk

- **Page background: graph paper** (`--paper`, `--paper-grid*`). The notebook page everything sits on.
  It stays faint so it never competes with text.
- **Dark mode: a chalkboard** with the same objects in darker paper. Tape and pins keep their colours.
- **Type stays the same:**
  - Bricolage Grotesque for headings;
  - Atkinson Hyperlegible Next for reading;
  - Atkinson Hyperlegible Mono only for data (weeks, dates, percentages).
  - No handwriting fonts. Readability is the product.

## Paper objects (and what each one means)

| Object | Looks like | Used for | Rule |
|---|---|---|---|
| **Taped slip** | Paper sheet (`--surface` with `--grain`, no outline) with two strips of translucent tape on its top corners | Main panels you work in: the plan, the add-course form, notes, setup | Never rotated. These hold reading text. |
| **Pinned card** | Index card held by a pushpin (round head and a steel needle), tilted by about a third of a degree at most. "Coming up" has the red index-card line under its heading | Concepts on the prerequisite map; the "Coming up" card | The pin's colour shows coverage: green = taught in a listed prerequisite, grey = probably, gold = not in the listed prerequisites, hollow = not confirmed. |
| **Sticky note** | Coloured note (`--note`) with one tape strip, tilted a fifth of a degree | The one thing to do next: "Start with a 3-minute check", important notices | At most one per screen, so it stays the obvious next step. |
| **Sticker** | Small rounded label with a paper-white outline and a soft lift | Course pills, coverage tags, source tags | Flat colour. The text keeps 4.5:1 contrast. |
| **Highlighter** | A marker stroke behind words | "Needed now" / "Already in use", and the key phrase of the home headline | Only for urgency or the single most important phrase. |
| **String** | Wool string pulled from pin to pin over the cards: a slight sag, darker twisted plies, light fibres, a fuzzy halo and a soft shadow | Links on the prerequisite map: from what you need first to what builds on it | Each source concept has its own string colour so you can follow it. Dashed (tacked) string = fewer than 2 of 3 mapping runs agreed. No arrowheads: direction comes from the columns, left to right. |

Every screen uses the same objects: the main panel of each tab is a taped slip; side panels ("Coming up",
"How matching works", "Worth class time soon") are pinned index cards; question cards and your uploaded notes
are smaller slips lying on the sheet; quotes from a syllabus are clippings taped into the concept drawer; the
concept drawer and the quick check are sheets laid on top. On the timeline, this week is highlighted and NOW is
written on tape.

The **How it works** page (`#/how`) uses the same objects: the live student-model demo is a taped slip with
pinned cards and strings; build stages are white index cards with number stickers; student steps are yellow
notes; each algorithm is a sheet with its formula (KaTeX); app screenshots are taped prints. "Watch it run" is a
browser window playing six scenes of the sample course on a loop (paused off screen, still under reduced motion);
the workflow cards light up in order while on screen; "Built with" is two looping rows of logo stickers
(Simple Icons, CC0), which stop and wrap under reduced motion.

Week headings in the plan are written on a short strip of tape. List rows are ruled like notebook paper (`--ruling`).

## The board (prerequisite map)

- **Sections:** each column is a section with invisible borders. Press, hold and drag a card anywhere
  inside its own column; the section outline shows only while dragging. Arrow keys move a focused card
  (Shift for bigger steps); Alt + arrow keys move its pin.
- **Touch:** a finger holds still for a moment (350 ms) before a card or pin follows it, so a swipe that starts
  on a card still scrolls the page and a quick tap still opens the concept. On phones the board sits in a
  window that pans in any direction, like a map, and the key is folded away; "Show as a list" is still below it.
- **Pins:** drag a pin anywhere on its card to change where its strings are tied. By default a pin sits in
  the strip above the text, on the side its strings leave from or arrive at.
- **Memory:** positions are remembered per student and course in the browser; "Reset layout" puts
  everything back. The last card moved stays on top.
- A plain click (no drag) still opens the concept.

## Phones

- The course header is compact: the week, AI policy and any warning stay; the schedule type and other ways in
  wait behind "Show sources and notes"; the prerequisite text is cut to two lines until then.
- Plan counts that are still zero are hidden, so before the first check you see only what's to do and how long.
- Touch targets are at least 44px. Text is at least 12px.

## Depth and motion

- **Paper lifts a little off the desk:** a soft shadow falling to the lower right, as if lit from the upper left (`--lift`).
  Paper has grain, no outline, and edges that are gently uneven: the paper is a layer under the content, cut by
  `--edge-mask` (small wave tiles repeated along each edge, so the wave is the same size on any sheet). Text is
  never distorted, and the shadow stays on the element so the mask doesn't clip it. Edges wave; they are never torn.
  Pinned cards sit slightly higher than taped slips. No hard block shadows; no glows.
- **Hovering a pinned card** straightens it and lifts it slightly. Its threads come forward and all
  other cards and threads fade, using paler ink rather than transparency so text stays readable.
- **Opening a drawer or the check** slides it in once. Reduced motion turns this into a fade.

## Colour

- **SF State purple** (`--accent`) for actions and focus; **gold** (`--gold`) for highlights.
- **String colours:** the chart palette `--c1`…`--c8`, which has a separate set for dark mode.
- **Paper tints:**
  - `--surface` for taped slips and cards;
  - `--note` for the sticky note;
  - `--tape` for tape, which is translucent so the paper shows through.
- **Highlighter** (`--highlight`): text on it uses `--late-ink`, which is red in light mode and plain ink in dark mode, where red on the highlighter is too dim.

## Don'ts

- Spiral binding, torn edges, coffee stains, paperclip clip-art.
- Rotating a taped slip, or tilting anything noticeably. Things sit almost straight; character comes from edges and texture.
- More than one sticky note per screen.
- A label above a heading. Put metadata under the title instead.
- Coloured side stripes on cards.
- Transparency used to dim text.
