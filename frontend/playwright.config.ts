import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests', timeout: 180000, workers: 1, reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:5173', channel: 'msedge', viewport: {width: 1440, height: 1000}, screenshot: 'only-on-failure', launchOptions: {args: ['--no-proxy-server']} },
  webServer: { command: 'pnpm dev', url: 'http://127.0.0.1:5173', reuseExistingServer: true, timeout: 30000 }
})
