import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';

let agentProcess;
let viteProcess;
let stopping = false;

async function agentIsRunning() {
  try {
    const response = await fetch('http://127.0.0.1:8000/api/health', { signal: AbortSignal.timeout(800) });
    return response.ok;
  } catch {
    return false;
  }
}

async function waitForAgent() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (await agentIsRunning()) return true;
    await delay(250);
  }
  return false;
}

function stop() {
  if (stopping) return;
  stopping = true;
  viteProcess?.kill();
  agentProcess?.kill();
}

process.on('SIGINT', stop);
process.on('SIGTERM', stop);

if (!(await agentIsRunning())) {
  agentProcess = spawn('python', ['aiops-agent/api_server.py'], { stdio: 'inherit' });
  if (!(await waitForAgent())) {
    console.error('IncidentIQ Python agent API did not start on port 8000.');
    stop();
    process.exitCode = 1;
  }
}

if (!stopping) {
  viteProcess = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '0.0.0.0'], { stdio: 'inherit' });
  viteProcess.on('exit', (code) => {
    if (!stopping) stop();
    process.exitCode = code ?? 0;
  });
}
