import os
import re
import requests
from flask import Flask, render_template, request, flash
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import time

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.urandom(24)

# Configuration
GOOGLE_API_KEY = 'AIzaSyAAAB5rWTPfrm8WQMlVzkfxFfZfNjwNCWo'  # Replace with real API key
CSE_ID = '3239e451474a04f35'           # Replace with real CSE ID
SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

# Enhanced search sources
SEARCH_SOURCES = {
    'linkedin': 'site:linkedin.com/in OR site:linkedin.com/pub',
    'twitter': 'site:twitter.com',
    'github': 'site:github.com',
    'pastebin': 'site:pastebin.com OR site:pastebin.com/raw',
    'facebook': 'site:facebook.com',
    'instagram': 'site:instagram.com',
    'reddit': 'site:reddit.com',
    'documents': 'filetype:pdf OR filetype:doc OR filetype:docx OR filetype:xls OR filetype:xlsx',
    'contacts': 'inurl:contact OR inurl:about OR inurl:staff'
}

def create_search_queries(target, domains=None):
    """Generate comprehensive search queries"""
    queries = []
    base_queries = [
        f'"{target}" "@*.*"',
        f'intext:"{target}" intext:"@*.*"',
        f'intitle:"{target}" email'
    ]
    
    # Add domain-specific queries
    if domains:
        for domain in domains:
            base_queries.extend([
                f'site:{domain} "{target}" email',
                f'site:{domain} "@{domain}" (email OR contact)'
            ])
    
    # Add source-specific queries
    for source, pattern in SEARCH_SOURCES.items():
        queries.extend([f'{pattern} "{target}" email', f'{pattern} "@*.*" "{target}"'])
    
    return base_queries + queries

def google_search(query, retries=3, delay=2):
    """Improved Google search with retries and rate limiting"""
    params = {
        'q': query,
        'key': GOOGLE_API_KEY,
        'cx': CSE_ID,
        'num': 3,  # Conservative to avoid rate limits
        'userIp': '127.0.0.1'  # Helps with rate limiting
    }
    
    headers = {'User-Agent': USER_AGENT}
    
    for attempt in range(retries):
        try:
            time.sleep(delay * (attempt + 1))  # Progressive delay
            response = requests.get(SEARCH_URL, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json().get('items', [])
        except requests.exceptions.RequestException as e:
            app.logger.warning(f"Attempt {attempt + 1} failed for query '{query}': {str(e)}")
            if attempt == retries - 1:
                app.logger.error(f"Final failure for query '{query}': {str(e)}")
                return []

def extract_emails(text):
    """Enhanced email extraction with validation"""
    emails = re.findall(EMAIL_REGEX, text)
    valid_emails = []
    for email in emails:
        email = email.lower()
        # Skip common false positives
        if not any(email.endswith(ext) for ext in ['.png', '.jpg', '.gif', '.svg']):
            # Skip email patterns that are too generic
            if not re.match(r'^(support|contact|help|info|admin|webmaster|hello)@', email):
                valid_emails.append(email)
    return valid_emails

def search_pastebin(target):
    """Specialized Pastebin search"""
    try:
        response = requests.get(
            'https://psbdmp.ws/api/v3/search/' + quote(target),
            headers={'User-Agent': USER_AGENT},
            timeout=5
        )
        if response.status_code == 200:
            return [item['content'] for item in response.json().get('data', [])]
    except Exception as e:
        app.logger.error(f"Pastebin search error: {str(e)}")
    return []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/email-harvest', methods=['GET', 'POST'])
def email_harvest():
    if request.method == 'POST':
        target = request.form.get('target', '').strip()
        custom_domains = request.form.get('custom_domains', '').strip()
        
        if not target:
            flash('Target is required', 'error')
            return render_template('email_harvest.html')
        
        try:
            # Process domains
            domains = []
            if custom_domains:
                domains = [d.strip() for d in custom_domains.split(',') if d.strip()]
            
            # Generate queries
            queries = create_search_queries(target, domains)
            
            # Execute searches
            results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(google_search, q) for q in queries]
                for future in futures:
                    try:
                        items = future.result()
                        if items:
                            results.extend(items)
                    except Exception as e:
                        app.logger.error(f"Search error: {str(e)}")
            
            # Specialized Pastebin search
            pastebin_content = search_pastebin(target)
            if pastebin_content:
                results.append({
                    'title': 'Pastebin Results',
                    'snippet': '\n'.join(pastebin_content),
                    'link': 'https://psbdmp.ws/'
                })
            
            # Process results
            emails = set()
            for item in results:
                text = f"{item.get('title', '')} {item.get('snippet', '')} {item.get('link', '')}"
                emails.update(extract_emails(text))
            
            if not emails:
                flash('No emails found for the given target', 'warning')
                return render_template('email_harvest.html')
            
            return render_template('email_results.html', 
                                target=target,
                                emails=sorted(emails),
                                count=len(emails),
                                sources=len(results))
            
        except Exception as e:
            app.logger.error(f"Error: {str(e)}")
            flash('An error occurred during search', 'error')
    
    return render_template('email_harvest.html')

if __name__ == '__main__':
    if not os.path.exists('templates'):
        os.makedirs('templates')
    if not os.path.exists('static'):
        os.makedirs('static')
    app.run(host='0.0.0.0', port=5000, debug=True)
