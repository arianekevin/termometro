import { spawn, spawnSync, type ChildProcess } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export const PROJECT = 'demo'
const PYTHON = process.env.PYTHON || 'python3'

const freePort = () =>
  new Promise<number>((resolve, reject) => {
    const s = createServer()
    s.once('error', reject)
    s.listen(0, '127.0.0.1', () => {
      const { port } = s.address() as { port: number }
      s.close(() => resolve(port))
    })
  })

// Seeds a fresh database, starts the real server on a free port, and returns the function that stops it and cleans up.
export default async function globalSetup() {
  const dir = mkdtempSync(join(tmpdir(), 'termometro-e2e-'))
  const port = await freePort()
  const env = {
    ...process.env,
    TERMOMETRO_NO_AUTH: '1',
    TERMOMETRO_HOST: '127.0.0.1',
    TERMOMETRO_PORT: String(port),
    TERMOMETRO_DB: join(dir, 't.db'),
    TERMOMETRO_LANGUAGE: 'pt-BR',
    TERMOMETRO_PROJECTS: JSON.stringify([{ name: PROJECT, key: 'tk', origins: ['http://x'] }]),
  }
  const seed = spawnSync(PYTHON, [join(__dirname, 'seed.py')], { env, encoding: 'utf8' })
  if (seed.status !== 0) throw new Error(`seed failed:\n${seed.stdout}${seed.stderr}`)

  const server: ChildProcess = spawn(PYTHON, [join(__dirname, '..', 'server', 'termometro.py')], { env, stdio: ['ignore', 'ignore', 'inherit'] })
  const base = `http://127.0.0.1:${port}`
  for (let i = 0; ; i++) {
    if (server.exitCode !== null) throw new Error('server exited at startup')
    if (i > 100) { server.kill(); throw new Error('server did not start') }
    try { if ((await fetch(base + '/')).ok) break } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100))
  }
  process.env.PANEL_URL = base // workers inherit the environment

  return async () => {
    server.kill()
    await new Promise((r) => (server.exitCode !== null ? r(null) : server.once('exit', r)))
    rmSync(dir, { recursive: true, force: true })
  }
}
