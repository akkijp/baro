export type Line = string

declare module 'claude-code' {
  interface PluginState {
    'baro-band': { line: Line }
  }
}
