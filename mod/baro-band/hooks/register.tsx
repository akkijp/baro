import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Line } from '../types'

// baro の計画の 1 行（ターミナルのステータスラインと同じもの）を、入力欄の上の帯に出す。
// 計画と計測は baro のまま。この mod は `baro statusline --no-chain` を呼んで描くだけ。

const line = atom({ plugin: 'baro-band', key: 'line' } as const, '' as Line)

// baro はバーに端末の色（ANSI）を付けて出す。帯ではそれを Text の色に置き換える
const COLORS: Record<string, string> = { '31': 'error', '32': 'success', '33': 'warning', '34': 'suggestion' }
const SGR = /\x1b\[([0-9;]*)m/g

type Run = { text: string; code: string }

function runs(text: string): Run[] {
  const out: Run[] = []
  let code = '0'
  let at = 0
  for (const m of text.matchAll(SGR)) {
    if (m.index > at) out.push({ text: text.slice(at, m.index), code })
    code = m[1] || '0'
    at = m.index + m[0].length
  }
  if (at < text.length) out.push({ text: text.slice(at), code })
  return out
}

const REFRESH_MS = 30_000 // 何も起きていない間も「終了予定」がずれないように描き直す間隔
const BARO = 'PATH="$HOME/.local/bin:$PATH"; exec baro statusline --no-chain --width "$1"'

let columns = 80
let running = false

async function refresh($: EngineInterface) {
  if (running) return
  running = true
  try {
    const sessionId = await $.session.id()
    const { exitCode, stdout } = await $.process.run(['/bin/sh', '-c', BARO, 'baro-band', String(columns)], {
      stdin: JSON.stringify({ session_id: sessionId }),
      timeoutMs: 5_000,
    })
    const text = exitCode === 0 ? stdout.trim() : ''
    if (text !== (await read($, line))) await update($, line, () => text)
  } catch {
    // baro が無い・遅いときは帯を出さないだけ
  } finally {
    running = false
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    void refresh($)
    $.clock.every(REFRESH_MS, () => refresh($))
    return started
  })

  // baro start / done は Bash から呼ばれるので、ツールが終わるたびに読み直す
  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    void refresh($)
    return result
  })

  on('prompt.submit', async ($, e, next) => {
    const result = await next(e)
    void refresh($)
    return result
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    void refresh($)
    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    // ターミナルは statusLine に同じ 1 行が出ているので重ねない
    if (e.surface === 'terminal' || e.props.hasSurvey) return next(e)

    if (e.props.bodyColumns !== columns) {
      columns = e.props.bodyColumns
      void refresh($)
    }

    const text = await read($, line)
    if (!text) return next(e)

    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="row">
        {runs(text).map(r =>
          r.code === '90' ? (
            <Text dimColor>{r.text}</Text>
          ) : (
            <Text color={COLORS[r.code]} wrap="truncate-end">
              {r.text}
            </Text>
          ),
        )}
      </Box>
    )
  })
}
