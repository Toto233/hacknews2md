# 01 - Make article image capture atomic and signal-aware

**What to build:** Daily collection continues to retain multiple useful article images under concurrent Windows execution, without losing images to file locks or reporting site avatars, placeholders, and decorative assets as failed editorial images.

**Blocked by:** None - can start immediately.

**Status:** completed

- [x] Concurrent image downloads and WebP/AVIF conversion cannot delete or replace a file while another handle is open.
- [x] Final article image paths are written atomically and collisions do not overwrite another in-flight image.
- [x] Known low-signal resources such as profile avatars, placeholders, and HN spacer assets are skipped before download without reducing the allowed useful image count.
- [x] Regression tests cover concurrent conversion, atomic finalization, and low-signal URL classification.
