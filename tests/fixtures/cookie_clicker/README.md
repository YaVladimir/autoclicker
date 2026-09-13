# Cookie Clicker image fixtures

These files exercise the detector against the real Cookie Clicker artwork and
rendered game UI instead of relying only on generated circles:

- `scene_baseline.jpg` is a clean game frame;
- `scene_golden.jpg` is the same view with a real golden-cookie shimmer;
- `gold_cookie.png` and `wrath_cookie.png` are the corresponding game sprites.

The scenes were rendered at 1280 × 800 from the unmodified web client in the
public `plasma4/cookieclicker` mirror at commit `88bfa8b`, then cropped to the
game area and JPEG-compressed. The source sprite files came from:

- <https://orteil.dashnet.org/cookieclicker/img/goldCookie.png>
- <https://orteil.dashnet.org/cookieclicker/img/wrathCookie.png>
- <https://github.com/plasma4/cookieclicker/tree/88bfa8b>

Cookie Clicker and its artwork are © Orteil/DashNet. These small fixtures are
included only for compatibility testing and are not covered by this project's
MIT license.
