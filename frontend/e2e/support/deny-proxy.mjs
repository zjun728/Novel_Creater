export const DENY_PROXY_SOURCE = String.raw`
const http = require('node:http')
const { appendFileSync } = require('node:fs')

const port = Number(process.argv[2])
const nonce = process.env.M2_BROWSER_RUN_NONCE
const ledgerPath = process.env.BROWSER_DENY_PROXY_LEDGER_PATH

const server = http.createServer((request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    response.writeHead(200, { 'content-type': 'application/json' })
    response.end(JSON.stringify({ browserRunNonce: nonce }))
    return
  }
  appendFileSync(ledgerPath, 'http-denied\n', 'utf8')
  response.writeHead(502, {
    connection: 'close',
    'content-type': 'text/plain; charset=utf-8',
  })
  response.end('outbound request denied')
})

server.on('connect', (_request, socket) => {
  appendFileSync(ledgerPath, 'connect-denied\n', 'utf8')
  socket.end(
    'HTTP/1.1 502 Bad Gateway\r\n'
      + 'Connection: close\r\n'
      + 'Content-Length: 0\r\n'
      + '\r\n',
  )
})

server.listen(port, '127.0.0.1')
`


export function assertDenyProxyLedger(value, {
  expectedHttpCount = 0,
  expectedConnectCount = 0,
} = {}) {
  if (
    !Number.isInteger(expectedHttpCount)
    || expectedHttpCount < 0
    || !Number.isInteger(expectedConnectCount)
    || expectedConnectCount < 0
  ) {
    throw new TypeError('deny proxy ledger expectation is invalid')
  }
  const entries = String(value).split(/\r?\n/u).filter(Boolean)
  if (entries.some(entry => !['http-denied', 'connect-denied'].includes(entry))) {
    throw new Error('deny proxy ledger did not match its closed contract')
  }
  const deniedHttpCount = entries.filter(entry => entry === 'http-denied').length
  const deniedConnectCount = entries.filter(entry => entry === 'connect-denied').length
  if (
    deniedHttpCount !== expectedHttpCount
    || deniedConnectCount !== expectedConnectCount
  ) {
    throw new Error('deny proxy ledger did not match its closed contract')
  }
  return {
    deniedHttpCount,
    deniedConnectCount,
    liveWebsiteAccessCount: 0,
  }
}
