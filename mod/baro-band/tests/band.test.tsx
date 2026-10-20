import { expect, test } from 'claude-code/testing'

const TAIL = ' 0/3 ｜ 今: 1 x（経過0分・残り約5分） ｜ 残り全体 約15分（17:05）'
const LINE = `\x1b[33m▓\x1b[0m\x1b[90m░░░░░░░░░\x1b[0m${TAIL}`
const TREE = [
  '📋 採用ページ',
  '   ⏳ 残り約 15分（終了予定 17:05） ・ 🕒 0分 / 全体 15分',
  '│                      経過/見込み',
  '├─ 1 調べる                 0/ 5分 ▓░░░░',
  '│   └─ 🟨 1.1 x             0/ 5分 ◀ 作業中',
  '└─ 2 作る                   -/10分 ░░░░░',
  '    └─ ⬜ 2.1 y             -/10分',
].join('\n')

const ran = (stdout: string, exitCode = 0) => ({
  value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

// argv の最後が幅なら statusline、セッション ID なら show
const baro = (argv: readonly string[]) => (argv[2]?.includes(' show') ? ran(`${TREE}\n`) : ran(`${LINE}\n`))

const BAND = {
  plugin: 'baro-band',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 10,
    bodyColumns: 60,
    scroll: { offset: 0, bodyRows: 9 },
    view: {},
  },
} as const

const PANE = {
  plugin: 'baro-band',
  component: 'Pane',
  requestId: 'baro-detail',
  props: { title: '作業の詳細', isFocused: true, bodyColumns: 100, placement: 'inline', scroll: { offset: 0, bodyRows: 20 }, view: {} },
} as const

const USAGE = {
  value: {
    startedAt: 0,
    context: { window: 200000, tokens: 82000, percent: 41 },
    rateLimits: [
      { kind: 'five_hour', percentUsed: 86, resetsAt: new Date(2026, 9, 20, 17, 30).toISOString() },
      { kind: 'seven_day', percentUsed: 31 },
    ],
    cost: { usd: 3.125 },
  },
}

const AGENTS = {
  value: [
    { id: 'a1', description: '調べる', type: 'Explore', status: 'running' },
    { id: 'a2', description: '直す', type: 'general-purpose', status: 'running' },
    { id: 'a3', description: '読む', type: 'Explore', status: 'completed' },
  ],
}

test('Desktop と VS Code には baro の 1 行を出し、ターミナルには出さない', async ($, on) => {
  const calls: { argv: readonly string[]; stdin?: string }[] = []
  on('session.id', () => ({ value: 'sess-1' }))
  on('process.run', (_, e) => {
    calls.push({ argv: e.argv, stdin: e.init?.stdin })
    return baro(e.argv)
  })
  on('tool.call', () => ({ result: {} }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })

  await $.tool.call({ tool: 'Bash', command: 'baro start 1' })

  for (const surface of ['desktop', 'vscode'] as const) {
    const ui = await $.ui.mount({ ...BAND, surface })
    // 色の指定は Text の色になり、文字としては出ない
    expect((await ui.find({ type: 'Text', text: /残り全体/ }))?.text).toBe(TAIL)
    expect((await ui.find({ type: 'Text', text: /▓/ }))?.text).toBe('▓')
    expect(await ui.find({ type: 'Button', key: 'baro-detail' })).toBeDefined()
    await ui.unmount()
  }
  expect(calls[0]?.stdin).toBe(JSON.stringify({ session_id: 'sess-1' }))
  expect(calls.some(c => c.argv[2]?.includes(' show') && c.argv[4] === 'sess-1')).toBe(true)

  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /残り全体/ })).toBeUndefined()
  expect((await ui.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine')
  await ui.unmount()
})

test('帯の幅が変わったら、その幅で baro を呼び直す', async ($, on) => {
  const widths: string[] = []
  on('session.id', () => ({ value: 'sess-1' }))
  on('process.run', (_, e) => {
    if (!e.argv[2]?.includes(' show')) widths.push(e.argv[e.argv.length - 1] ?? '')
    return baro(e.argv)
  })
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  await ui.unmount()

  expect(widths).toContain('60')
})

test('baro が無い・計画が無いときは帯を出さない', async ($, on) => {
  on('session.id', () => ({ value: 'sess-1' }))
  on('process.run', () => ran('', 127))
  on('tool.call', () => ({ result: {} }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })

  await $.tool.call({ tool: 'Bash', command: 'ls' })

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Text', text: /残り全体/ })).toBeUndefined()
  expect((await ui.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine')
  await ui.unmount()
})

test('2 行目に使用量とサブエージェントを出し、使用率が高いと色を変える', async ($, on) => {
  on('session.id', () => ({ value: 'sess-1' }))
  on('process.run', () => ran('', 127))
  on('session.usage', () => USAGE)
  on('agent.list', () => AGENTS)
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>engine</Text>
  })

  // 計画が無くても、使用量の行は出す（ターミナルでも）
  for (const surface of ['desktop', 'terminal'] as const) {
    const ui = await $.ui.mount({ ...BAND, surface })
    expect((await ui.find({ type: 'Text', text: '5時間枠 86%（17:30リセット）' }))?.props.color).toBe('warning')
    expect((await ui.find({ type: 'Text', text: '週 31%' }))?.props.color).toBe('subtle')
    expect(await ui.find({ type: 'Text', text: 'コンテキスト 41%' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: '$3.13' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'サブエージェント 実行中2・完了1' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /残り全体/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('「詳細」を押すとペインが開き、baro show の木が出る', async ($, on) => {
  on('session.id', () => ({ value: 'sess-1' }))
  on('process.run', (_, e) => baro(e.argv))
  on('session.usage', () => USAGE)
  on('tool.call', () => ({ result: {} }))
  const opened: string[] = []
  on('ui.open', (_, e) => {
    opened.push(e.id)
    return { value: { isPlaced: true } }
  })

  await $.tool.call({ tool: 'Bash', command: 'baro start 1' })

  const band = await $.ui.mount({ ...BAND, surface: 'desktop' })
  await band.press({ key: 'baro-detail' })
  await band.unmount()
  expect(opened).toEqual(['baro-detail'])

  const pane = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect(await pane.find({ type: 'Text', text: '📋 採用ページ' })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: '│   └─ 🟨 1.1 x             0/ 5分 ◀ 作業中' })).toBeDefined()
  expect(await pane.find({ type: 'Text', text: /コンテキスト 41%/ })).toBeDefined()
  await pane.unmount()
})
