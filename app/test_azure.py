import os, json, requests
endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
deploy = os.getenv('AZURE_OPENAI_DEPLOYMENT')
key = os.getenv('AZURE_OPENAI_API_KEY')
if not endpoint or not key or not deploy:
    print('MISSING_ENV', endpoint, deploy, bool(key))
else:
    url = f"{endpoint.rstrip('/')}" + f"/openai/deployments/{deploy}/chat/completions?api-version=2024-02-15-preview"
    payload = {"messages": [{"role":"user","content":"Say hello"}], "max_tokens":10}
    headers = {'api-key': key, 'Content-Type': 'application/json'}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        print('URL:', url)
        print('STATUS', r.status_code)
        try:
            print('JSON:', json.dumps(r.json(), indent=2)[:2000])
        except Exception:
            print('TEXT:', r.text[:1000])
    except Exception as e:
        print('ERR', e)
