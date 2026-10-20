import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Line } from '../types'

// 入力欄の上の帯に 2 行を出す。
//   1 行目: baro の計画の 1 行（ターミナルのステータスラインと同じもの）と「詳細」ボタン
//   2 行目: 使用量（5 時間枠・週・コンテキスト・費用）とサブエージェントの数
// 「詳細」を押すと、`baro show` の木をペインに出す。
// 計画と計測は baro のまま。この mod は baro を呼んで描くだけ。

const line = atom({ plugin: 'baro-band', key: 'line' } as const, '' as Line)
const detail = atom({ plugin: 'baro-band', key: 'detail' } as const, '' as Line)

const PANE_ID = 'baro-detail'
const REFRESH_MS = 30_000 // 何も起きていない間も「終了予定」がずれないように描き直す間隔
const SH = 'PATH="$HOME/.local/bin:$PATH"; '
const BARO_LINE = SH + 'exec baro statusline --no-chain --width "$1"'
const BARO_SHOW = SH + 'exec baro --session "$1" show'

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

let columns = 80
let running = false

async function refresh($: EngineInterface) {
  if (running) return
  running = true
  try {
    const sessionId = await $.session.id()
    const stdin = JSON.stringify({ session_id: sessionId })
    const a = await $.process.run(['/bin/sh', '-c', BARO_LINE, 'baro-band', String(columns)], { stdin, timeoutMs: 5_000 })
    const text = a.exitCode === 0 ? a.stdout.trim() : ''
    if (text !== (await read($, line))) await update($, line, () => text)
    let tree = ''
    if (text) {
      const b = await $.process.run(['/bin/sh', '-c', BARO_SHOW, 'baro-band', sessionId], { timeoutMs: 5_000 })
      tree = b.exitCode === 0 ? b.stdout.trimEnd() : ''
    }
    if (tree !== (await read($, detail))) await update($, detail, () => tree)
  } catch {
    // baro が無い・遅いときは帯を出さないだけ
  } finally {
    running = false
  }
}

// ---- 使用量・サブエージェント ----

type Part = { text: string; pct: number | null }

const pctColor = (pct: number | null): string => (pct === null ? 'subtle' : pct >= 95 ? 'error' : pct >= 80 ? 'warning' : 'subtle')

const clockOf = (iso: string | undefined): string => {
  if (iso === undefined) return ''
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return ''
  const d = new Date(t)
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function usageParts($: EngineInterface): Promise<Part[]> {
  try {
    const u = await $.session.usage()
    const parts: Part[] = []
    for (const r of u.rateLimits) {
      const label = r.kind === 'five_hour' ? '5時間枠' : r.kind === 'seven_day' ? '週' : r.kind === 'spend_limit' ? '支出上限' : r.kind
      const at = r.kind === 'five_hour' ? clockOf(r.resetsAt) : ''
      parts.push({ text: `${label} ${Math.round(r.percentUsed)}%${at === '' ? '' : `（${at}リセット）`}`, pct: r.percentUsed })
    }
    if (u.context.percent !== undefined) parts.push({ text: `コンテキスト ${u.context.percent}%`, pct: u.context.percent })
    if (u.cost !== undefined) parts.push({ text: `$${u.cost.usd.toFixed(2)}`, pct: null })
    return parts
  } catch {
    return []
  }
}

type Agents = { line: string; rows: string[] }

async function agentsOf($: EngineInterface): Promise<Agents | null> {
  try {
    const list = await $.agent.list()
    const running = list.filter(a => a.status === 'running' || a.status === 'pending' || a.status === 'waiting')
    if (running.length === 0) return null
    const done = list.filter(a => a.status === 'completed').length
    const failed = list.filter(a => a.status === 'failed' || a.status === 'killed').length
    const tail = [done > 0 ? `完了${done}` : '', failed > 0 ? `失敗${failed}` : ''].filter(x => x !== '').join('・')
    const rows = list.map(a => {
      const mark = a.status === 'completed' ? '🟩' : a.status === 'failed' || a.status === 'killed' ? '🟥' : '🟨'
      return `${mark} ${a.description}（${a.type}）`
    })
    return { line: `サブエージェント 実行中${running.length}${tail === '' ? '' : '・' + tail}`, rows }
  } catch {
    return null
  }
}

async function openDetail($: EngineInterface): Promise<void> {
  void refresh($)
  await $.ui.open({ id: PANE_ID, title: '作業の詳細', focus: true, closeOnEscape: true })
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
    if (e.props.hasSurvey) return next(e)

    if (e.props.bodyColumns !== columns) {
      columns = e.props.bodyColumns
      void refresh($)
    }

    // ターミナルは statusLine に同じ 1 行が出ているので、計画の行は重ねない
    const text = e.surface === 'terminal' ? '' : await read($, line)
    const parts = await usageParts($)
    const agents = await agentsOf($)
    if (!text && parts.length === 0 && agents === null) return next(e)

    const { Box, Text, Button } = $.ui.resolve(e)

    let top: ReturnType<typeof Box> | null = null
    if (text) {
      top = (
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
          <Text> </Text>
          <Button key={PANE_ID} label="詳細" plain dimColor onPress={() => openDetail($)} />
        </Box>
      )
    }

    let bottom: ReturnType<typeof Box> | null = null
    if (parts.length > 0 || agents !== null) {
      const items: ReturnType<typeof Text>[] = []
      for (const p of parts) {
        if (items.length > 0) items.push(<Text dimColor>{' ｜ '}</Text>)
        items.push(<Text color={pctColor(p.pct)}>{p.text}</Text>)
      }
      if (agents !== null) {
        if (items.length > 0) items.push(<Text dimColor>{' ｜ '}</Text>)
        items.push(<Text color="suggestion">{agents.line}</Text>)
      }
      bottom = <Box flexDirection="row">{...items}</Box>
    }

    return (
      <Box flexDirection="column">
        {top}
        {bottom}
      </Box>
    )
  })

  // 詳細ペイン: baro show の木・サブエージェント・使用量
  on('ui.render', { component: 'Pane', requestId: PANE_ID }, async ($, e) => {
    const tree = await read($, detail)
    const parts = await usageParts($)
    const agents = await agentsOf($)
    const { Box, Text } = $.ui.resolve(e)
    const rows = tree
      ? tree.split('\n').map((l, i) => (
          <Text key={`l${i}`} wrap="truncate-end">
            {l}
          </Text>
        ))
      : [<Text dimColor>計画はありません</Text>]
    return (
      <Box flexDirection="column" gap={1}>
        <Box flexDirection="column">{...rows}</Box>
        {agents === null ? null : (
          <Box flexDirection="column">
            <Text bold>{agents.line}</Text>
            {...agents.rows.map((r, i) => (
              <Text key={`a${i}`} dimColor>
                {r}
              </Text>
            ))}
          </Box>
        )}
        {parts.length === 0 ? null : <Text dimColor>{parts.map(p => p.text).join(' ｜ ')}</Text>}
      </Box>
    )
  })
}
