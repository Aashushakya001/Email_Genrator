# import re

# def clean_text(text):
#     # Remove HTML tags
#     text = re.sub(r'<[^>]*?>', '', text)
#     # Remove URLs
#     text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
#     # Remove special characters
#     text = re.sub(r'[^a-zA-Z0-9 ]', '', text)
#     # Replace multiple spaces with a single space
#     text = re.sub(r'\s{2,}', ' ', text)
#     # Trim leading and trailing whitespace
#     text = text.strip()
#     # Remove extra whitespace
#     text = ' '.join(text.split())
#     return text


"""
utils.py — Text cleaning for scraped web content.

ROOT CAUSE FIX:
  Old clean_text used re.sub(r'[^a-zA-Z0-9 ]', '', text) which stripped:
    - '@' → broke all email addresses
    - '://' → broke all URLs (LinkedIn, GitHub, company sites)
    - '.' → broke domain names
  This caused contact_email, linkedin, github to all return NULL.

New clean_text only removes HTML markup and collapses whitespace.
All emails, URLs, phone numbers, and punctuation are preserved.
"""

from __future__ import annotations

import re


def clean_text(text: str) -> str:
    """Clean scraped HTML/web text for LLM consumption.

    Removes:  HTML tags, <script>, <style> blocks, non-printable chars
    Keeps:    Email addresses, URLs, phone numbers, punctuation, newlines

    Do NOT strip URLs or special characters — that breaks email/LinkedIn
    extraction downstream.
    """
    if not text:
        return ""

    # Remove <script> and <style> blocks including their content
    text = re.sub(r"<script[^>]*?>.*?</script>", " ", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<style[^>]*?>.*?</style>", " ", text, flags=re.DOTALL | re.I)

    # Remove all remaining HTML tags (keep inner text)
    text = re.sub(r"<[^>]{1,500}?>", " ", text)

    # Remove non-printable / control characters (keep standard ASCII + newlines)
    text = re.sub(r"[^\x09\x0A\x0D\x20-\x7E]", " ", text)

    # Collapse excessive horizontal whitespace
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Collapse excessive blank lines (keep max 2 consecutive newlines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()