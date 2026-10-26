# UI-review mode: visual and accessibility review

`dt` is the platform's device tool: `adt` on Android, `idt` on iOS.

Goal: a picky, evidence-backed review of how the screens look and how accessible they are.
Choose the screens with the user (or from the charter); go through each one the same way.

## Per screen

1. `dt observe --name <screen> --bounds --full` (positions and sizes for the target checks) and look at the full-size screenshot, not only the preview.
2. Accessibility (from the element tree):
   - Touch targets at least 48x48 dp on Android (dp = px * 160 / dpi, density from `adt info`), 44x44 pt on iOS (`idt` sizes are already in points).
   - Every control has a label; icons and image buttons have a content description (Android) or accessibility label (iOS); decorative images don't (a label read twice is a finding).
   - Checkboxes, switches and inputs are labelled by their own text or description, not only by a neighbouring text.
   - Controls are exposed as controls: on iOS a tappable image or text without the button trait shows up as `Image` or `StaticText`, not `Button`, and VoiceOver won't say it can be activated.
   - `sr-only` texts (Android): present where visible text is drawn as an image, and saying the same as what's shown.
   - Hidden controls still in the tree (behind other controls) are focusable traps for screen readers.
   - Contrast of text against its background at least 4.5:1 (3:1 for large text): sample colours from the screenshot crop.
3. Visual (pixel-picky; Material 3 conventions on Android, Apple's Human Interface Guidelines on iOS):
   - Overlaps: cards or banners covering navigation, clipped text, content under system bars.
   - Alignment, spacing and typography consistent with the rest of the app.
   - Truncation and wrapping with real data; empty, loading and error states.
4. Content and localisation:
   - One language per screen, including image descriptions.
   - Number, decimal and date formats of the locale ("1,99" vs "3.75").
   - Consistent tone (formal vs informal) and copy that matches the controls it refers to.
   - Terms used the way `about.glossary` defines them, and the same term for the same thing everywhere.

Crop evidence to the problem area and keep the full screenshot next to it.

## Config stress (emulator or simulator, or a phone only with approval)

Font size largest (Dynamic Type on iOS), display size largest, dark mode, landscape, RTL language.
Use `adt env --font-scale 2.0 --dark on --orientation landscape --rtl on` or `idt env --text-size accessibility-extra-extra-extra-large --dark on`: they record the original settings, and `env --reset` or `session end` restores them.
On a test device or emulator they need no approval; on a personal phone each is listed in the plan, and Go approves them (`--approval "session plan: ..."`).

## Screen reader (optional)

TalkBack on Android, VoiceOver on iOS: only on an emulator or simulator, or with the user's approval (it changes how the device behaves).
Check focus order and what is announced for the main journey.
Without running it, say in the finding that it was judged from the element tree only.
