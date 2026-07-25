import { readFile, writeFile } from 'node:fs/promises'
import { renderPresentation } from './render.mjs'

// Render one JSON DeckSpec to a PPTX file for local validation and diagnostics.
const main = async () => {
  const [, , inputPath, outputPath] = process.argv
  if (!inputPath || !outputPath) {
    throw new Error('Usage: npm run render -- input.json output.pptx')
  }
  const specification = JSON.parse(await readFile(inputPath, 'utf8'))
  const content = await renderPresentation(specification)
  await writeFile(outputPath, content)
}

await main()
