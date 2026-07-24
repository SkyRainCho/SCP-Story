import os

# Page fetching is parallelized via a thread pool by default (see
# _fetch_worker_count). Thread-completion order is non-deterministic, which
# would make the many tests that assert fetch call ORDER flaky. Run the fetch
# path serially during tests; the parallel path is exercised by its own test.
os.environ.setdefault("SCP_EPUB_FETCH_WORKERS", "1")
