import os
import re
import json
import asyncio
import logging
from urllib.parse import urljoin, urlparse
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options
from tqdm import tqdm
import cssutils
import aiohttp
import platform

# Suppress cssutils warnings about modern CSS properties
cssutils.log.setLevel(logging.ERROR)

class SiteScraper:
    def __init__(self, base_url, output_dir="scraped_site", interactive=False):
        self.base_url = base_url
        # Create a safe folder name from the URL
        safe_folder_name = re.sub(r'[^\w\-_]', '_', urlparse(base_url).netloc)
        self.output_dir = Path(output_dir) / safe_folder_name
        self.visited_urls = set()
        self.session = requests.Session()
        self.downloaded_files = set()
        self.interactive = interactive
        self.setup_logging()
        self.setup_selenium()
        
    def setup_logging(self):
        os.makedirs('logs', exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(Path('logs') / 'scraper.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def setup_selenium(self):
        options = uc.ChromeOptions()
        if not self.interactive:
            options.add_argument("--headless")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
        
        try:
            if self.interactive:
                self.driver = uc.Chrome(
                    options=options,
                    use_subprocess=True,
                    headless=False
                )
            else:
                self.driver = uc.Chrome(
                    options=options,
                    use_subprocess=False,
                    headless=True
                )
            self.logger.info("Chrome initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Chrome: {str(e)}")
            raise

    def create_directory_structure(self, url_path):
        """Create necessary directory structure for saving files."""
        if not url_path or url_path == '/':
            return self.output_dir / 'index.html'
        
        # Parse the URL and get the path
        parsed_url = urlparse(url_path)
        path = parsed_url.path.lstrip('/')
        
        # Remove query parameters from filename if they exist
        path = path.split('?')[0]
        
        # Create the full path while maintaining the original structure
        full_path = self.output_dir / path
        
        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        return full_path

    async def download_resource(self, url, session):
        if url in self.downloaded_files:
            return None
            
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.read()
                    
                    if not url.startswith(self.base_url) and not url.startswith('/'):
                        return content
                    
                    if url.startswith(self.base_url):
                        url_path = url[len(self.base_url):]
                    else:
                        url_path = url
                    
                    save_path = self.create_directory_structure(url_path)
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    
                    with open(save_path, 'wb') as f:
                        f.write(content)
                    self.downloaded_files.add(url)
                    self.logger.info(f"Downloaded: {url} -> {save_path}")
                    return content
                else:
                    self.logger.warning(f"Failed to download {url}: Status {response.status}")
        except Exception as e:
            self.logger.error(f"Error downloading {url}: {str(e)}")
        return None

    def analyze_javascript(self, js_content, base_url):
        resources = set()
        path_vars = {}
        var_assignments = re.finditer(r'(?:const|let|var)\s+(\w+)\s*=\s*[\'"]([^\'"\s]+)[\'"]', js_content)
        for match in var_assignments:
            var_name, value = match.groups()
            path_vars[var_name] = value

        dynamic_paths = re.finditer(r'(?:const|let|var)\s+(\w+)\s*=\s*\{([^}]+)\}', js_content)
        for match in dynamic_paths:
            var_name, content = match.groups()
            pairs = re.finditer(r'(\w+):\s*[\'"]([^\'"\s]+)[\'"]', content)
            for pair in pairs:
                key, value = pair.groups()
                path_vars[f"{var_name}.{key}"] = value

        patterns = [
            r'(?:src|href|url):\s*[\'"]([^\'"\s]+)[\'"]',
            r'(?:load|fetch|import)\s*\([\'"]([^\'"\s]+)[\'"]',
            r'new\s+(?:Image|Audio)\([\'"]([^\'"\s]+)[\'"]',
            r'\.load\s*\([\'"]([^\'"\s]+)[\'"]',
            r'\.loadTexture\s*\([\'"]([^\'"\s]+)[\'"]',
            r'\.setPath\s*\([\'"]([^\'"\s]+)[\'"]',
            r'`([^`]+?\.(?:mp3|wav|ogg|glb|gltf|jpg|png))`',
            r'\.join\s*\([\'"]([^\'"\s]+)[\'"]',
            r'\.resolve\s*\([\'"]([^\'"\s]+)[\'"]',
            r'[\'"](/[^\'"\s]+\.(?:js|css|png|jpg|jpeg|gif|svg|mp3|wav|json|wasm|glb|gltf|bin|basis|ktx2|drc|ico))[\'"]'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, js_content)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                if match and not match.startswith(('http://', 'https://', 'data:', 'blob:', 'javascript:')):
                    match = match.strip('\'"`')
                    if match.startswith('./'):
                        match = match[2:]
                    for var_name, var_value in path_vars.items():
                        if var_name in match:
                            match = match.replace(var_name, var_value)
                    resources.add(urljoin(base_url, match))

        imports = re.finditer(r'(?:import|require)\s*\(\s*[\'"]([^\'"\s]+)[\'"]', js_content)
        for match in imports:
            path = match.group(1)
            if not path.startswith(('http://', 'https://', 'data:', 'blob:')):
                resources.add(urljoin(base_url, path))

        return resources

    def extract_resources(self, soup, base_url):
        resources = set()
        
        for script in soup.find_all('script', src=True):
            script_url = urljoin(base_url, script['src'])
            resources.add(script_url)
            try:
                response = requests.get(script_url)
                if response.status_code == 200:
                    js_resources = self.analyze_javascript(response.text, base_url)
                    resources.update(js_resources)
            except Exception as e:
                self.logger.error(f"Error analyzing script {script_url}: {str(e)}")
        
        for script in soup.find_all('script'):
            if script.string:
                js_resources = self.analyze_javascript(script.string, base_url)
                resources.update(js_resources)
        
        for css in soup.find_all('link', rel='stylesheet'):
            if css.get('href'):
                css_url = urljoin(base_url, css['href'])
                resources.add(css_url)
                try:
                    response = requests.get(css_url)
                    if response.status_code == 200:
                        css_content = response.text
                        url_patterns = [
                            r'url\([\'"]?([^\'"\)]+)[\'"]?\)',
                            r'@import\s+[\'"]([^\'"\s]+)[\'"]'
                        ]
                        for pattern in url_patterns:
                            matches = re.findall(pattern, css_content)
                            for match in matches:
                                if not match.startswith(('http://', 'https://', 'data:', 'blob:')):
                                    resources.add(urljoin(base_url, match))
                except Exception as e:
                    self.logger.error(f"Error analyzing CSS {css_url}: {str(e)}")
        
        for tag in soup.find_all(['img', 'video', 'audio', 'source', 'model-viewer', 'canvas']):
            for attr in ['src', 'data-src', 'srcset', 'href', 'data-model', 'data-texture']:
                if tag.get(attr):
                    if attr == 'srcset':
                        for src_str in tag[attr].split(','):
                            url = src_str.strip().split()[0]
                            resources.add(urljoin(base_url, url))
                    else:
                        resources.add(urljoin(base_url, tag[attr]))
        
        for meta in soup.find_all('meta'):
            if meta.get('content') and meta.get('content').startswith(('/','http')):
                if any(key in str(meta) for key in ['image', 'video', 'audio', 'model']):
                    resources.add(urljoin(base_url, meta['content']))
        
        for tag in soup.find_all(True):
            for attr in tag.attrs:
                if isinstance(tag[attr], str):
                    if any(ext in tag[attr].lower() for ext in ['.glb', '.gltf', '.bin', '.jpg', '.png', '.basis']):
                        resources.add(urljoin(base_url, tag[attr]))
        
        return resources

    async def process_page(self, url):
        if url in self.visited_urls:
            return
        
        self.visited_urls.add(url)
        self.logger.info(f"Processing page: {url}")
        
        try:
            self.driver.get(url)
            
            if self.interactive:
                print("\nBrowser is open for interactive exploration.")
                print("Navigate the site to expose dynamic content.")
                print("Commands:")
                print("  done    - Start scraping the current state")
                print("  help    - Show this help message")
                print("  url     - Show current URL")
                print("  wait    - Wait 5 more seconds for loading")
                print("  refresh - Refresh the page")
                
                while True:
                    user_input = input("> ").strip().lower()
                    if user_input == 'done':
                        break
                    elif user_input == 'help':
                        print("\nCommands:")
                        print("  done    - Start scraping the current state")
                        print("  help    - Show this help message")
                        print("  url     - Show current URL")
                        print("  wait    - Wait 5 more seconds for loading")
                        print("  refresh - Refresh the page")
                    elif user_input == 'url':
                        print(f"Current URL: {self.driver.current_url}")
                    elif user_input == 'wait':
                        print("Waiting 5 seconds...")
                        self.driver.execute_script("return new Promise(resolve => setTimeout(resolve, 5000));")
                        print("Done waiting")
                    elif user_input == 'refresh':
                        print("Refreshing page...")
                        self.driver.refresh()
                        self.driver.execute_script("return new Promise(resolve => setTimeout(resolve, 2000));")
                        print("Page refreshed")
            else:
                # Wait for initial page load
                self.driver.execute_script("""
                    return new Promise((resolve) => {
                        if (document.readyState === 'complete') {
                            setTimeout(resolve, 2000);
                        } else {
                            window.addEventListener('load', () => setTimeout(resolve, 2000));
                        }
                    });
                """)
            
            # Additional wait for dynamic content
            self.driver.execute_script("""
                return new Promise((resolve) => {
                    const start = performance.now();
                    const checkResources = () => {
                        const pending = performance.getEntriesByType('resource')
                            .filter(r => !r.responseEnd);
                        if (pending.length === 0 || performance.now() - start > 10000) {
                            resolve();
                        } else {
                            setTimeout(checkResources, 100);
                        }
                    };
                    checkResources();
                });
            """)
            
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')
            
            url_path = urlparse(url).path
            if not url_path:
                url_path = 'index.html'
            elif not url_path.endswith('.html'):
                url_path = os.path.join(url_path, 'index.html')
                
            save_path = self.create_directory_structure(url_path)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(page_source)
            
            page_resources = self.extract_resources(soup, url)
            resources = set(page_resources)
            
            loaded_resources = self.driver.execute_script("""
                const resources = new Set();
                performance.getEntriesByType('resource').forEach(entry => {
                    resources.add(entry.name);
                });
                
                const getElementResources = (tagName, attrs) => {
                    return Array.from(document.getElementsByTagName(tagName))
                        .map(el => attrs.map(attr => el[attr]))
                        .flat()
                        .filter(url => url && !url.startsWith('data:') && !url.startsWith('blob:'));
                };
                
                [
                    ['script', ['src']],
                    ['link', ['href']],
                    ['img', ['src', 'currentSrc']],
                    ['audio', ['src']],
                    ['video', ['src']],
                    ['source', ['src']],
                    ['object', ['data']],
                    ['embed', ['src']]
                ].forEach(([tag, attrs]) => {
                    getElementResources(tag, attrs).forEach(url => resources.add(url));
                });
                
                return Array.from(resources);
            """)
            
            for resource in loaded_resources:
                if resource:
                    resources.add(resource)
            
            self.logger.info(f"Found {len(resources)} resources to download")
            
            async with aiohttp.ClientSession() as session:
                tasks = [self.download_resource(res, session) for res in resources]
                with tqdm(total=len(tasks), desc="Downloading resources") as pbar:
                    for task in asyncio.as_completed(tasks):
                        await task
                        pbar.update(1)
            
            if not self.interactive:
                for link in soup.find_all('a', href=True):
                    next_url = urljoin(url, link['href'])
                    if (next_url.startswith(self.base_url) and 
                        next_url not in self.visited_urls and 
                        not next_url.endswith(('.pdf', '.jpg', '.png', '.gif'))):
                        await self.process_page(next_url)
                    
        except Exception as e:
            self.logger.error(f"Error processing {url}: {str(e)}")
            raise

    async def scrape(self):
        self.logger.info(f"Starting scrape of {self.base_url}")
        os.makedirs(self.output_dir, exist_ok=True)
        
        try:
            await self.process_page(self.base_url)
            self.logger.info(f"Scraping completed! Downloaded {len(self.downloaded_files)} files")
            self.logger.info(f"Files saved in: {self.output_dir}")
        finally:
            self.driver.quit()

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Scrape a website including all resources.')
    parser.add_argument('url', help='The base URL to scrape')
    parser.add_argument('--output', default='scraped_site', help='Output directory')
    parser.add_argument('--interactive', '-i', action='store_true', help='Open browser for interactive exploration before scraping')
    args = parser.parse_args()
    
    if platform.system() == 'Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    scraper = SiteScraper(args.url, args.output, args.interactive)
    asyncio.run(scraper.scrape())

if __name__ == "__main__":
    main() 