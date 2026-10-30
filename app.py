"""DarkSight dashboard: click a button, watch the TinyFish agent work live.

    python app.py      -> http://localhost:8000
"""
import asyncio, json, os, pathlib, threading, time, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import re
import agent
from detect import report
from report import complaint

ROOT = pathlib.Path(__file__).parent
JOBS = {}  # ponytail: in-memory job table, fine for one local user


def summary(ev):
    return report(ev)


def start_job(name, sc, signed_in=False):
    job = {"id": uuid.uuid4().hex[:8], "name": name, "platform": sc["platform"], "status": "running",
           "live": None, "steps": 0, "log": [f"$ python agent.py {name}", f"→ TinyFish agent launched · stealth browser · {sc['url']}"]}
    JOBS[job["id"]] = job

    def on_event(kind, data):
        if kind == "live":
            job["live"] = data
            job["log"].append("→ live browser view ready")
        else:
            job["steps"] += 1
            job["log"].append(f"  step {job['steps']:>2}  {data}")

    def work():
        t = time.time()
        try:
            ev = asyncio.run(agent.run_one(name, sc, on_event, signed_in))
            job.update(status="done", **summary(ev))
            if agent.needs_login(ev):  # hit a login wall: the UI offers "sign in yourself, then retry"
                job["needs_login"] = agent.host_of(sc["url"])
                job["log"].append(f"🔐 {job['needs_login']} needs a login before it shows the bill")
            job["log"].append(f"■ stopped before payment · {ev['agent_steps']} steps · {time.time() - t:.0f}s")
            job["log"].append(f"✓ saved evidence/{name}.json · grade {job['grade']}")
        except Exception as e:
            job["status"] = "failed"
            job["log"].append(f"✗ {e}")

    threading.Thread(target=work, daemon=True).start()
    return job


def scenarios():
    out = []
    for name, sc in agent.SCENARIOS.items():
        f = ROOT / "evidence" / f"{name}.json"
        last = summary(json.loads(f.read_text())) if f.exists() else None
        out.append({"name": name, "platform": sc["platform"], "category": sc["category"], "url": sc["url"], "last": last})
    return out


class Handler(BaseHTTPRequestHandler):
    def send(self, body, ctype="application/json", code=200):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            return self.send((ROOT / "ui.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/scenarios":
            return self.send(scenarios())
        if self.path.startswith("/complaint/"):  # printable complaint letter -> browser "Save as PDF"
            name = self.path.rsplit("/", 1)[-1]
            f = ROOT / "evidence" / f"{name}.json"
            if re.fullmatch(r"\w+", name) and f.exists():
                return self.send(complaint(json.loads(f.read_text())).encode(), "text/html; charset=utf-8")
            return self.send({"error": "no evidence for that run"}, code=404)
        if self.path.startswith("/api/job/"):
            job = JOBS.get(self.path.rsplit("/", 1)[-1])
            return self.send(job or {"error": "unknown job"}, code=200 if job else 404)
        self.send({"error": "not found"}, code=404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/run":
            signed_in = bool(body.get("signed_in"))
            if body.get("scenario") in agent.SCENARIOS:
                return self.send(start_job(body["scenario"], agent.SCENARIOS[body["scenario"]], signed_in))
            if str(body.get("url", "")).startswith("http"):
                return self.send(start_job(*agent.scenario_for(body["url"]), signed_in))
            return self.send({"error": "pick a scenario or give an http(s) url"}, code=400)
        if self.path == "/api/login":  # TinyFish sign-in page; the user types their own details there
            try:
                return self.send(agent.login_link(str(body.get("host", ""))))
            except Exception as e:
                return self.send({"error": f"could not create a TinyFish profile: {e}"}, code=502)
        if self.path == "/api/discover":
            try:
                return self.send(agent.discover(body.get("query") or "online grocery delivery Bangalore", n=5))
            except Exception as e:
                return self.send({"error": str(e)}, code=502)
        self.send({"error": "not found"}, code=404)

    def log_message(self, *a):  # keep the terminal quiet
        pass


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print(f"DarkSight dashboard → http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
