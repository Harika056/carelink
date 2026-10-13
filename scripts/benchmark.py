"""Measure read latency/throughput of a running CareLink server (your own machine, your own numbers).

    python scripts/benchmark.py --base-url http://127.0.0.1:8000 --requests 2000 --threads 8
"""
import argparse
import http.client
import json
import statistics
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

_local = threading.local()  # one keep-alive connection per thread (no new socket per request)


def get(url):
    u = urllib.parse.urlsplit(url)
    path = u.path + ("?" + u.query if u.query else "")
    for attempt in (1, 2):
        conn = getattr(_local, "conn", None)
        if conn is None:
            conn = _local.conn = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status} for {path}")
            return json.loads(body)
        except (http.client.HTTPException, OSError):
            conn.close()
            _local.conn = None
            if attempt == 2:
                raise


def timed(url):
    t = time.perf_counter()
    get(url)
    return (time.perf_counter() - t) * 1000


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p / 100))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--requests", type=int, default=2000)
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args()
    ids = [e["resource"]["id"] for e in get(f"{a.base_url}/Patient?_count=100")["entry"]]
    if not ids:
        raise SystemExit("No patients found. Run scripts/seed.py first.")
    urls = []
    for i in range(a.requests):
        pid = ids[i % len(ids)]
        urls.append([f"{a.base_url}/Patient/{pid}", f"{a.base_url}/Observation?patient={pid}",
                     f"{a.base_url}/Patient/{pid}/$screening"][i % 3])
    for u in urls[:50]:  # warm-up, not measured
        get(u)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.threads) as ex:
        lat = list(ex.map(timed, urls))
    wall = time.perf_counter() - t0
    print(f"requests: {len(lat)}  threads: {a.threads}  (mix: read patient / search observations / screening)")
    print(f"throughput: {len(lat) / wall:.0f} req/s")
    print(f"latency ms  p50={statistics.median(lat):.1f}  p95={pct(lat, 95):.1f}  p99={pct(lat, 99):.1f}")


if __name__ == "__main__":
    main()
