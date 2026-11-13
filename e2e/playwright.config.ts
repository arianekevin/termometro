import { defineConfig } from '@playwright/test'

// Locally, PW_CHROMIUM_PATH can point at a browser binary already on the machine; CI uses the one `playwright install` fetched.
const executablePath = process.env.PW_CHROMIUM_PATH || undefined

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.ts',
  globalSetup: './global-setup.ts',
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4,
  retries: 0,
  timeout: 30_000,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  use: {
    locale: 'pt-BR',
    launchOptions: { executablePath },
  },
})
