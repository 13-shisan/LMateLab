# Public Pages and Typography Adjustment

## Scope

- Increase Dashboard content typography without changing the approved sidebar density.
- Make authentication pages fit 360px and wider mobile viewports without horizontal clipping.
- Keep the existing home hero image and copy while improving CTA hierarchy and mobile navigation.

## Design

Dashboard body text moves to a 12-14px readable scale, panel titles to 16px, and the welcome title to 24px. Card dimensions remain stable so information density is preserved.

Authentication pages use their own neutral header instead of the dashboard topbar. On mobile, secondary header links are hidden, the login card is centered with 16px viewport gutters, desktop offsets are reset, and the footer remains in normal flow.

The home hero keeps its material illustration. The primary `了解平台` action uses teal with a compass icon; `进入登录` uses dark navy with a login icon. Both actions retain full text and become evenly sized on mobile.

## Verification

- CSS contract tests guard the mobile offset reset and Dashboard font floor.
- Production build, focused ESLint, unit tests, and npm audit must pass.
- Playwright checks 1440x900 desktop and 390x844 mobile for `/`, `/login`, and `/dashboard`.
