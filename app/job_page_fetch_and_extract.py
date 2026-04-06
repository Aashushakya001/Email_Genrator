import requests
import re

URL = "https://www.accenture.com/in-en/careers/jobdetails?id=ATCI-4822077-S1849385_en"

def fetch(url):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JobExtractor/1.0)"}
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text

def heuristic_extract(page_text: str):
    role = None
    location = None
    # Attempt common patterns
    m_role = re.search(r"(?im)(?:Job Title|Position|Role)[:\-]\s*(.+)", page_text)
    if m_role:
        role = m_role.group(1).strip()
    # Try <title> or <h1>
    if not role:
        m_title = re.search(r"<title\s*>([^<]+)</title>", page_text, flags=re.I)
        if m_title:
            role = m_title.group(1).strip()
    if not role:
        m_h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", page_text, flags=re.I)
        if m_h1:
            role = m_h1.group(1).strip()
    # Look for Location
    m_loc = re.search(r"(?im)(?:Location)[:\-]\s*(.+)", page_text)
    if m_loc:
        location = m_loc.group(1).strip()
    # Try meta location tags or labels
    if not location:
        m_meta_loc = re.search(r"<meta[^>]+name=[\'\"]?location[\'\"]?[^>]+content=[\'\"]([^\'\"]+)[\'\"]", page_text, flags=re.I)
        if m_meta_loc:
            location = m_meta_loc.group(1).strip()
    return {"role": role, "location": location}

if __name__ == '__main__':
    try:
        page = fetch(URL)
        print('Fetched bytes:', len(page))
        # print small snippet
        print(page[:1000])
        extracted = heuristic_extract(page)
        print('Heuristic extraction:', extracted)
    except Exception as e:
        print('Error fetching or extracting:', e)
