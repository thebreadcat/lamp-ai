# Font Awesome Free 6.7.2

Icons in Lamp use [Font Awesome Free](https://fontawesome.com) (self-hosted for offline PWA use).

- CSS: `css/all.min.css`
- Webfonts: `webfonts/`
- License: [LICENSE.txt](LICENSE.txt) (Icons: CC BY 4.0; Fonts: SIL OFL 1.1; Code: MIT)

To refresh assets, run from the repo root:

```bash
curl -fsSL "https://github.com/FortAwesome/Font-Awesome/releases/download/6.7.2/fontawesome-free-6.7.2-web.zip" -o /tmp/fa-free.zip
unzip -qo /tmp/fa-free.zip "fontawesome-free-6.7.2-web/css/all.min.css" "fontawesome-free-6.7.2-web/webfonts/*" -d /tmp/fa-extract
cp /tmp/fa-extract/fontawesome-free-6.7.2-web/css/all.min.css css/
cp /tmp/fa-extract/fontawesome-free-6.7.2-web/webfonts/* webfonts/
cp /tmp/fa-extract/fontawesome-free-6.7.2-web/LICENSE.txt .
```
