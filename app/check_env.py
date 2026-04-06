import os
print('AZURE_OPENAI_API_KEY set?', bool(os.getenv('AZURE_OPENAI_API_KEY')))
print('AZURE_OPENAI_ENDPOINT set?', bool(os.getenv('AZURE_OPENAI_ENDPOINT')))
print('AZURE_OPENAI_DEPLOYMENT:', os.getenv('AZURE_OPENAI_DEPLOYMENT'))
