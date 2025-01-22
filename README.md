# site scraper

a robust web scraper that downloads entire websites with all their resources, maintaining the original directory structure.

## features
- downloads all site resources (js, css, images, 3d models, audio, etc.)
- interactive mode for sites with dynamic content
- maintains original directory structure
- handles javascript-rendered content
- cross-platform (windows, macos, linux)

## installation

```bash
git clone https://github.com/getyoursnackon/site-scraper.git
cd site-scraper
pip install -r requirements.txt
```

## usage

basic scraping:
```bash
python site_scraper.py https://example.com
```

interactive mode (for sites with dynamic content):
```bash
python site_scraper.py -i https://example.com
```

custom output directory:
```bash
python site_scraper.py https://example.com --output my_sites
```

## interactive mode commands
- `done` - start scraping the current state
- `help` - show help message
- `url` - show current url
- `wait` - wait 5 more seconds for loading
- `refresh` - refresh the page

## requirements
- python 3.7+
- chrome browser
- see requirements.txt for python packages 