# PH Engagement Bot - TODO

## Known Issues

(No critical issues)

## Planned Improvements

### [ ] Retry logic for failed comments
- If comment fails, retry after 5s
- Max 2 retries per post

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
- [x] **Comment posting fix** (2026-02-04)
  - Root cause: PH uses TipTap/ProseMirror contenteditable div, not textarea
  - Fix: Added `div.tiptap.ProseMirror` selector, use `.type()` instead of `.fill()`
  - Added pre-comment screenshot for debugging
  - **Tested and confirmed working** - successfully posted comment on Dottie product
  - Added auto-conversion from `/products/` to `/posts/` URL (comments only work on /posts/)
- [x] **Mac Mini daemon setup** (2026-02-05)
  - Added `scripts/install-daemon.sh` for launchd setup
  - Added `scripts/uninstall-daemon.sh`
  - Documentation for nohup, launchd, tmux options
