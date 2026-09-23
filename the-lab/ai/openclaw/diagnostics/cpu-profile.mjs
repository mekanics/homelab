// Captures a V8 CPU profile of the OpenClaw gateway's main thread and every Node
// worker thread, then prints self-time per function. Diagnoses the idle ~1.4-core
// burn documented in the-lab/ai/openclaw/values.yaml.
//
// Requires the inspector to already be listening. Do NOT `kill -USR1 1` to open
// it — OpenClaw traps SIGUSR1 as its own restart signal. Instead add --inspect to
// NODE_OPTIONS in values.yaml, roll the deploy, then:
//
//   kubectl -n openclaw cp the-lab/ai/openclaw/diagnostics/cpu-profile.mjs \
//     "$(kubectl -n openclaw get pod -l app.kubernetes.io/name=openclaw \
//        -o jsonpath='{.items[0].metadata.name}')":/tmp/prof.mjs -c gateway
//   kubectl -n openclaw exec deploy/openclaw -c gateway -- node /tmp/prof.mjs
//
// The gateway is throttled, so sampling costs it real time; keep PROF_MS modest.

const DURATION_MS = Number(process.env.PROF_MS || 20000);

const list = await (await fetch('http://127.0.0.1:9229/json/list')).json();
const wsUrl = list[0]?.webSocketDebuggerUrl;
if (!wsUrl) throw new Error('no inspector target: ' + JSON.stringify(list));

const ws = new WebSocket(wsUrl);
await new Promise((res, rej) => {
  ws.addEventListener('open', res, { once: true });
  ws.addEventListener('error', rej, { once: true });
});

let nextId = 1;
const pending = new Map();
const workers = new Map(); // sessionId -> title

ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    return;
  }
  if (msg.method === 'NodeWorker.attachedToWorker') {
    workers.set(msg.params.sessionId, msg.params.workerInfo?.title || 'worker');
  }
});

function send(method, params = {}, sessionId) {
  const id = nextId++;
  const payload = { id, method, params };
  if (sessionId) payload.sessionId = sessionId;
  ws.send(JSON.stringify(payload));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

// Worker threads are separate inspector targets; NodeWorker surfaces them as sessions.
await send('NodeWorker.enable', { waitForDebuggerOnStart: false });
await new Promise((r) => setTimeout(r, 1500));

const targets = [{ sessionId: undefined, label: 'MainThread' }];
for (const [sessionId, title] of workers) targets.push({ sessionId, label: `Worker:${title}` });

for (const t of targets) {
  await send('Profiler.enable', {}, t.sessionId);
  await send('Profiler.setSamplingInterval', { interval: 1000 }, t.sessionId);
  await send('Profiler.start', {}, t.sessionId);
}

console.log(`profiling ${targets.length} target(s) for ${DURATION_MS}ms: ${targets.map((t) => t.label).join(', ')}`);
await new Promise((r) => setTimeout(r, DURATION_MS));

for (const t of targets) {
  let profile;
  try {
    ({ profile } = await send('Profiler.stop', {}, t.sessionId));
  } catch (err) {
    console.log(`\n### ${t.label}: stop failed: ${err.message}`);
    continue;
  }

  const byNode = new Map();
  const { samples = [], timeDeltas = [], nodes = [] } = profile;
  for (let i = 0; i < samples.length; i++) {
    byNode.set(samples[i], (byNode.get(samples[i]) || 0) + (timeDeltas[i] || 0));
  }

  const frames = new Map();
  let total = 0;
  for (const node of nodes) {
    const us = byNode.get(node.id) || 0;
    if (!us) continue;
    total += us;
    const f = node.callFrame;
    const where = f.url ? `${f.url.replace(/^file:\/\//, '')}:${f.lineNumber + 1}` : '';
    const key = `${f.functionName || '(anonymous)'}  ${where}`;
    frames.set(key, (frames.get(key) || 0) + us);
  }

  console.log(`\n### ${t.label} — ${(total / 1000).toFixed(0)}ms sampled across ${samples.length} samples`);
  const ranked = [...frames].sort((a, b) => b[1] - a[1]).slice(0, 25);
  for (const [key, us] of ranked) {
    console.log(`${((us / total) * 100).toFixed(1).padStart(5)}%  ${(us / 1000).toFixed(0).padStart(6)}ms  ${key}`);
  }
}

ws.close();
