import { expect, test } from 'claude-code/testing'

const TAIL = ' 0/3 ｜ 今: 1 x（経過0分・残り約5分） ｜ 残り全体 約15分（17:05）'
const LINE = `\x1b[33m▓\x1b[0m\x1b[90m░░░░░░░░░\x1b[0m${TAIL}`

const ran = (stdout: string, exitCode = 0) => ({
  value: { exitCode, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

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

test('Desktop と VS Code には baro の 1 行を出し、ターミナルには出さない', async ($, on) => {
  const calls: { argv: readonly string[]; stdin?: string }[] = []
  on('session.id', () => ({ value: 'sess-1' }))
  on('process.run', (_, e) => {
    calls.push({ argv: e.argv, stdin: e.init?.stdin })
    return ran(`${LINE}\n`)
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
    await ui.unmount()
  }
  expect(calls[0]?.stdin).toBe(JSON.stringify({ session_id: 'sess-1' }))

  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /残り全体/ })).toBeUndefined()
  expect((await ui.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine')
  await ui.unmount()
})

test('帯の幅が変わったら、その幅で baro を呼び直す', async ($, on) => {
  const widths: string[] = []
  on('session.id', () => ({ value: 'sess-1' }))
  on('process.run', (_, e) => {
    widths.push(e.argv[e.argv.length - 1] ?? '')
    return ran(LINE)
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
