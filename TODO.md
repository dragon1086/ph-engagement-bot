# PH Engagement Bot - TODO

## Known Issues

### [ ] Comment posting fails while like succeeds
- **Status**: Investigating
- **Symptom**: `/ph_execute` shows "Liked: Yes | Commented: No"
- **Possible causes**:
  1. Comment textarea selector not matching (PH UI may have changed)
  2. Submit button selector not found
  3. Comment input requires click/focus before typing
  4. Rate limiting on comments
- **Debug steps**:
  - Check screenshot for comment input visibility
  - Verify selectors in `browser_driver.py:post_comment()`
  - Test with browser DevTools to find correct selectors

```python
# Current selectors in post_comment()
comment_selectors = [
    'textarea[placeholder*="comment"]',
    'textarea[placeholder*="Comment"]',
    '[data-test="comment-input"]',
    '.comment-form textarea',
    'div[contenteditable="true"]',
]
```

## Planned Improvements

### [ ] Better comment selector detection
- Use Playwright's inspector to find current PH comment input
- Add fallback for contenteditable div

### [ ] Retry logic for failed comments
- If comment fails, retry after 5s
- Max 2 retries per post

### [ ] Screenshot before/after comment
- Take screenshot before attempting comment
- Helps debug selector issues

## Completed

- [x] Firecrawl integration for JS-rendered scraping
- [x] Korean translations in approval UI
- [x] Simplified approval buttons (#1/#2/#3 direct approve)
- [x] Playwright stealth mode
- [x] Persistent Chrome profile
- [x] CAPTCHA detection and notification
- [x] Full product description fetching
- [x] CLAUDE.md documentation
- [x] Architecture documentation
