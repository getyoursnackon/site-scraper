# Site Scraper

A robust web scraper that downloads entire websites with all their resources, maintaining the original directory structure.

## Features
- Downloads all site resources (JS, CSS, images, 3D models, audio, etc.)
- Interactive mode for sites with dynamic content
- Maintains original directory structure
- Handles JavaScript-rendered content
- Cross-platform (Windows, macOS, Linux)

## Installation

```bash
git clone [your-repo-url]
cd site-scraper
pip install -r requirements.txt
```

## Usage

Basic scraping:
```bash
python site_scraper.py https://example.com
```

Interactive mode (for sites with dynamic content):
```bash
python site_scraper.py -i https://example.com
```

Custom output directory:
```bash
python site_scraper.py https://example.com --output my_sites
```

## Interactive Mode Commands
- `done` - Start scraping the current state
- `help` - Show help message
- `url` - Show current URL
- `wait` - Wait 5 more seconds for loading
- `refresh` - Refresh the page

## Requirements
- Python 3.7+
- Chrome browser
- See requirements.txt for Python packages 