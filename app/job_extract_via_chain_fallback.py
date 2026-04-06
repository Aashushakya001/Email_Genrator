import importlib
import sys
import pathlib
# ensure repo root on sys.path when running script directly
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.job_page_fetch_and_extract import fetch

def run():
    page = fetch("https://www.accenture.com/in-en/careers/jobdetails?id=ATCI-4822077-S1849385_en")
    print('Fetched bytes:', len(page))

    # Create a Chain instance without running __init__ so we can test the fallback path
    import app.chains as chains_mod
    Chain = chains_mod.Chain
    obj = object.__new__(Chain)
    # minimal attributes used by extract_jobs
    obj.deployment = getattr(obj, 'deployment', 'gpt-35-turbo')
    obj.azure_key = None
    obj.endpoint = None
    obj.last_error = None

    # bind a call_llm that raises a '413' style exception to force the fallback
    def _raise(*a, **kw):
        raise Exception('413 Request Entity Too Large')

    obj.call_llm = _raise

    # call extract_jobs which should hit the fallback heuristic and return parsed list
    jobs = obj.extract_jobs(page)
    print('Extracted jobs:', jobs)

if __name__ == '__main__':
    run()
