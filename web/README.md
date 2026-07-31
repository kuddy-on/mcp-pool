# MCPPool dashboard

The dashboard is a React and TypeScript administration client served by an unprivileged nginx
container. nginx proxies `/api/` to the gateway service.

```bash
npm ci
npm run dev
npm run lint
npm test
npm run build
npm run e2e
```

Authentication tokens are stored in `sessionStorage`, so they survive a reload in the current tab
but are removed when the tab closes. Logout also calls the gateway revocation endpoint.

Vitest covers the authentication state and Playwright exercises login and logout in desktop and
mobile Chromium viewports.

The production container listens on port 8080 and sends a restrictive Content Security Policy,
clickjacking protection, MIME-sniffing protection, and privacy-oriented browser headers.
