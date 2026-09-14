# Cookie Clicker image fixtures

These files exercise the detector against the real Cookie Clicker artwork and
rendered game UI instead of relying only on generated circles:

- `scene_baseline.jpg` is a clean game frame;
- `scene_golden.jpg` is the same view with a real golden-cookie shimmer;
- `gold_cookie.png` and `wrath_cookie.png` are the corresponding game sprites.
- `scene_yellow_milk.png` is a user-provided 2552 × 1364 screenshot used to
  reproduce a missed golden cookie over bright yellow milk. It is kept
  lossless because JPEG compression changes the hue boundaries under test.
- `scene_cookie_background.png` is a second user-provided screenshot, at
  2550 × 1357, with a golden cookie blending into the ordinary-cookie backdrop.
  Tests also remove that target to check rejection of bright background cookies
  and white building icons before calibration.
- `scene_overlapping_ui.png` is a third user-provided screenshot, at
  2557 × 1377, where a golden cookie overlaps banks, a horizontal border and
  spell icons. It tests detection when neither colour nor highlight contours
  form a separate blob, plus delivery through the watcher to the click callback.
- `scene_wrath.png` is a user-provided 2542 × 1414 screenshot with a red wrath
  cookie over the grandma background. The negative test replaces it with a
  neighbouring repeated background patch to check for clicks on red decoration.
- `scene_wrath_red_background.png` is a user-provided 2558 × 1338 screenshot
  where a wrath cookie blends into a red grandma background and its circular
  edge was missed at a single smoothing scale. Tests also remove the cookie
  to reject chocolate chips and wrinklers, and composite the reference sprite
  at other positions, sizes and rotations on that background.

The baseline and golden JPEG scenes were rendered at 1280 × 800 from the unmodified web client in the
public `plasma4/cookieclicker` mirror at commit `88bfa8b`, then cropped to the
game area and JPEG-compressed. The source sprite files came from:

- <https://orteil.dashnet.org/cookieclicker/img/goldCookie.png>
- <https://orteil.dashnet.org/cookieclicker/img/wrathCookie.png>
- <https://github.com/plasma4/cookieclicker/tree/88bfa8b>

Cookie Clicker and its artwork are © Orteil/DashNet. These small fixtures are
included only for compatibility testing and are not covered by this project's
MIT license.
