# baro メインビジュアル

- 用途: README 冒頭のメインビジュアル
- 生成方法: built-in `image_gen` tool
- 画像: `baro-hero.png`
- 補足: 実画面のスクリーンショットではなく、残り時間・終了予定・進捗を伝えるコンセプトビジュアル。

## 生成プロンプト

```text
Use case: ads-marketing
Asset type: GitHub README main visual, wide landscape banner approximately 2:1, high resolution.
Primary request: Create an elegant, memorable main visual for "baro", a small Japanese CLI utility showing remaining work time and progress for Claude Code. It reads estimated task steps, displays remaining minutes, expected finish time, and a segmented green/yellow progress bar in the terminal status line.
Style: exceptionally polished editorial graphic design with subtle paper grain and crisp typography; warm ivory background, charcoal terminal, muted forest green and warm amber accents. Quiet, useful developer-tool character. Flat front-facing composition, with restrained soft shadows and some subtle physical depth in the progress blocks. No sci-fi, no glowing neon.
Composition: generous margins. Top left large lowercase wordmark "baro" with a small ten-cell progress motif nearby. Beneath the wordmark the Japanese headline "あと何分か、ひと目で。" in beautiful clear Japanese sans-serif. A smaller subtitle "Claude Code の作業に、残り時間を。" Lower half features one broad dark charcoal terminal panel, beautifully typeset, a small header "baro", with a subdued minimal task tree above and a visually prominent status strip below. Terminal content should be sparse and readable, not dense.
Text (verbatim, prioritize accurate Japanese):
baro
あと何分か、ひと目で。
Claude Code の作業に、残り時間を。
Terminal task tree:
✓ 調べる
› 作る
  仕上げ
Status strip:
残り約 26分
終了予定 15:12
41%
Progress strip has exactly ten separated square cells: four green completed cells, one amber current cell, five muted gray remaining cells. The large "26" and readable progress strip form the visual focal point. The 41% is an estimate, avoid implying exact linear measurement.
Constraints: all text spelled accurately; product name lowercase baro; no invented features, no analytics charts, no browser mockups, no people, no stock illustration, no other company logos, no watermarks. This is a conceptual product visual, not a claim of pixel-perfect app screenshot. Finish as a cohesive designed banner with ample breathing room.
```
