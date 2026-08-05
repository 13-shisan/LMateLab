# Dashboard Equal Panel Height

## Scope

Align the bottom edge of the desktop Dashboard academic-reports panel with the bottom edge of the main content column. Do not change card content, typography, column widths, or mobile stacking behavior.

## Design

The two-column Dashboard grid owns row height, so it should stretch both direct children to the height of the taller column. The reports panel fills its grid area naturally. No fixed pixel height and no JavaScript measurement are introduced.

At the existing `1120px` breakpoint, the Dashboard becomes a single column. Panels then keep their natural content height so the reports panel does not leave unnecessary blank space on tablets and mobile devices.

## Verification

- A CSS contract test guards desktop grid stretching and the single-column natural-height reset.
- Playwright measures both desktop panel bottoms at `1440x900` and requires them to match.
- The Dashboard is checked at a narrow viewport for normal stacking, clipping, and overflow.
- Unit tests and the production build must pass before deployment.
